"""Resolve, statically, the calls that the executable's protection wrapper redirected.

The user's own copy (AGENTS.md allows working around the protection of a legitimately
owned copy). Nothing of the wrapper is executed; the port replaces both mechanisms:

1. `call 0x400080` (91 sites): a stub in the PE header looks the return address
   up in a table of (IAT slot, return address) pairs that ends at 0x40087c and jumps
   to the import. The table is in the file, so every site resolves exactly; the
   runtime (runtime/protection_redirect.c) reads it from the mapped image.
2. `call dword ptr [0x850000]` (37 sites): a slot in .prus filled at run time. Each
   site is classified here from the surrounding code, with strict patterns:
   - get_last_error: the result is compared with a Win32 error code right after a
     failed API call, or handed to the CRT's _dosmaperr (0x655150), or tested after
     TlsGetValue in the CRT's per-thread data (0x612eb0).
   - validate_pointer: `push size; push pointer; call; test eax,eax` in the CRT's
     exception-handling code, where a non-zero result aborts (IsBad*Ptr semantics).
   - integrity: an anti-tamper check whose caller loads magic values in registers and
     then requires one answer, `cmp eax, K; je ok` (else it sets a penalty flag): the
     port answers K, as the wrapper of an intact copy does.
   - resume: the caller loads `esi` with a label a few bytes ahead and falls through into a
     penalty (writes a flag) when the call returns normally: the intact wrapper removes its
     stdcall arguments and continues at that label.
   - mirror: a decoy call. On the stack, above the return address, a header the wrapper
     removes (a decoy function address, or `4` and a buffer) and a triple A, M, B pushed by
     the caller (B first), which the caller pops itself. The intact wrapper returns B and,
     when M is a pointer (from `lea`), stores B there; the caller checks either.
   - store: the register form: eax/ecx magic, ebx a pointer (`lea`); the wrapper stores ecx
     at [ebx] (the caller then requires that variable to be non-zero).
   - bounded: `push 4; push buffer` and the caller takes its clean path when the result is
     at most K (`cmp eax, K; ... jle clean`): the wrapper returns 0 and removes the two arguments.
   - trigger: anything else. These stay fail-closed until each is analysed.
Output: private/analysis/protection/redirects.json and redirect_sites.h (private).
"""
import hashlib,json,re,struct
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,EXPECTED
STUB,TABLE_END,SLOT=0x400080,0x40087c,0x850000
STUB_BYTES=bytes.fromhex('83ec04508b4424088944240458608b4424' '20ba7c08400033dbeb14390413750c8b4413fc8b0089442420eb0983eb08833c130075e661c3')
ERROR_CODES={0x2:'ERROR_FILE_NOT_FOUND',0x26:'ERROR_HANDLE_EOF',0xb7:'ERROR_ALREADY_EXISTS',0x3e5:'ERROR_IO_PENDING'}
DOSMAPERR,ABORT,GETPTD_SITE=0x655150,0x66bd60,0x612ec6
def mirror(prev,text_range):
    """(B, header argument count, M is a pointer) for the decoy-call layout, else None."""
    pushes=[(k,i) for k,i in enumerate(prev[-9:]) if i.mnemonic=='push']
    window=prev[-9:]
    if len(pushes)<3:return None
    ops=[i.op_str for _,i in pushes]
    def imm(o):return o.startswith('0x') and int(o,16)
    if imm(ops[-1]) and text_range[0]<=imm(ops[-1])<text_range[1]:header=1
    elif len(ops)>=5 and ops[-2]=='4' and not ops[-1].startswith('0x'):header=2
    else:header=0
    triple=ops[-3-header:len(ops)-header] if header else ops[-3:]
    if len(triple)!=3 or not imm(triple[0]) or not imm(triple[2]):return None
    b,m=imm(triple[0]),triple[1]
    write=not m.startswith('0x') and any(i.mnemonic=='lea' and i.op_str.split(',')[0]==m for i in window)
    return b,header,write
def resume_target(prev,site):
    """(label, stdcall argument count) when the call site is `mov esi, label` + pushes + call, esi is not
    written again, and the label lies just past the call (the code in between is the penalty)."""
    for k in range(len(prev)-1,max(len(prev)-5,-1),-1):
        i=prev[k]
        if i.mnemonic=='mov' and i.op_str.startswith('esi, 0x'):
            target=int(i.op_str.split(', ')[1],16);after=prev[k+1:]
            if not site<target<=site+0x40:return None
            if any(j.op_str.split(',')[0].strip()=='esi' and j.mnemonic not in ('push',) for j in after):return None
            if any(j.mnemonic!='push' and j.mnemonic!='mov' for j in after):return None
            return target,sum(1 for j in after if j.mnemonic=='push')
        if i.op_str.split(',')[0].strip()=='esi' and i.mnemonic!='push':return None
    return None
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    pe=pefile.PE(data=data);base=pe.OPTIONAL_HEADER.ImageBase
    if data[STUB-base:STUB-base+len(STUB_BYTES)]!=STUB_BYTES:raise SystemExit('header stub differs from the analysed one')
    iat={imp.address:(e.dll.decode().lower(),imp.name.decode() if imp.name else f'ordinal_{imp.ordinal}') for e in pe.DIRECTORY_ENTRY_IMPORT for imp in e.imports}
    text=pe.get_data(0x1000,0x26d200);md=Cs(CS_ARCH_X86,CS_MODE_32);text_range=(0x401000,0x66e200)
    # 1. Header table: walk it exactly as the stub does (downwards from TABLE_END until a zero return address).
    table=[];at=TABLE_END
    while True:
        ret=struct.unpack_from('<I',data,at-base)[0]
        if not ret:break
        slot=struct.unpack_from('<I',data,at-4-base)[0]
        if slot not in iat:raise SystemExit(f'header entry {at:#x} points at {slot:#x}, not an import slot')
        table.append({'return':hex(ret),'slot':hex(slot),'import':'!'.join(iat[slot])});at-=8
    calls={0x401000+i+5 for i in range(len(text)-5)
           if text[i]==0xe8 and (0x401000+i+5+struct.unpack_from('<i',text,i+1)[0])&0xffffffff==STUB}
    returns={int(t['return'],16) for t in table}
    if len({t['return'] for t in table})!=len(table):raise SystemExit('duplicate return address in header table')
    if calls!=returns:raise SystemExit(f'header table/call sites mismatch: {len(calls)} calls, {len(returns)} entries')
    # 2. Slot sites.
    def window(site,before=0x40,after=24):
        for back in range(before,0,-1):
            ins=list(md.disasm(text[site-0x401000-back:site-0x401000+after],site-back))
            idx=[i for i,x in enumerate(ins) if x.address==site]
            if idx and all(ins[k].address+ins[k].size==ins[k+1].address for k in range(len(ins)-1)):return ins[:idx[0]],ins[idx[0]+1:]
        raise SystemExit(f'cannot decode around {site:#x}')
    def api_call(i):
        if i.mnemonic=='call' and i.op_str.startswith('dword ptr [0x'):
            a=int(i.op_str[11:-1],16);return iat.get(a,(None,None))[1]
        if i.mnemonic=='call' and i.op_str==hex(STUB):
            return iat[int(next(t['slot'] for t in table if int(t['return'],16)==i.address+i.size),16)][1]
        return None
    def pointer_args(prev):
        """The two arguments pushed right before the call (size first, then pointer), allowing
        register set-up between them that does not touch the stack."""
        pushed=[]
        for i in reversed(prev[-5:]):
            if i.mnemonic=='push':pushed.append(i.op_str)
            elif i.mnemonic in('mov','add','movsx','lea') and 'esp' not in i.op_str:continue
            else:break
            if len(pushed)==2:break
        if len(pushed)!=2:return None
        size=pushed[1]
        if not(size in('1','4','8','0x18') or size in('ecx','edx')):return None
        return size,pushed[0]
    sites=[]
    for m in re.finditer(rb'\xff\x15'+struct.pack('<I',SLOT),text):
        site=0x401000+m.start();prev,nxt=window(site);kind=None;evidence=''
        prior=[api_call(i) for i in prev[-8:] if api_call(i)]
        pushes=pointer_args(prev)
        if nxt[0].mnemonic=='cmp' and nxt[0].op_str.startswith('eax, ') and int(nxt[0].op_str[5:],16) in ERROR_CODES:
            kind='get_last_error';evidence=(f'{prior[-1]} failed, ' if prior else 'after a failed CRT read, ')+f'result compared with {ERROR_CODES[int(nxt[0].op_str[5:],16)]}'
        elif nxt[0].mnemonic=='push' and nxt[0].op_str=='eax' and nxt[1].mnemonic=='call' and nxt[1].op_str==hex(DOSMAPERR):
            kind='get_last_error';evidence='result passed to _dosmaperr 0x655150'
        elif site==GETPTD_SITE and prior and prior[-1]=='TlsGetValue' and nxt[0].op_str=='eax, eax':
            kind='get_last_error';evidence='TlsGetValue returned 0 in the CRT per-thread data; non-zero result is an error'
        elif (prior and prior[-1]=='DuplicateHandle' and nxt[0].mnemonic=='pop' and nxt[1].mnemonic=='ret'
              and prev[-1].mnemonic=='mov' and prev[-1].op_str=='dword ptr [ebx], 0xffffffff'):
            kind='get_last_error';evidence='DuplicateHandle failed; result returned as the error code'
        elif (pushes and 0x653000<=site<0x66c000 and nxt[0].mnemonic=='test' and nxt[0].op_str=='eax, eax'
              and (any(i.mnemonic=='call' and i.op_str==hex(ABORT) for i in nxt[:6])
                   or (nxt[1].mnemonic=='jne' and nxt[2].op_str.startswith('eax, dword ptr [ebp'))
                   or (nxt[1].mnemonic=='jne' and nxt[2:4] and nxt[2].op_str=='1' and nxt[3].op_str.startswith('dword ptr [ebp')))):
            kind='validate_pointer';evidence=f'IsBad*Ptr({pushes[1]}, {pushes[0]}) in CRT exception handling'
        elif nxt[0].mnemonic=='cmp' and nxt[0].op_str.startswith('eax, ') and nxt[0].op_str[5:].replace('0x','').isalnum() and nxt[1].mnemonic=='je' and int(nxt[1].op_str,16)>nxt[1].address:
            kind='integrity';value=int(nxt[0].op_str.split(', ')[1],0)
            evidence=f'anti-tamper check: the caller requires eax == {value:#x} (else it sets a penalty flag) || '+' ; '.join(f'{i.mnemonic} {i.op_str}' for i in prev[-6:]+nxt[:3])
        elif mirror(prev,text_range) is not None:
            value,args,write=mirror(prev,text_range);kind='mirror'
            evidence=f'decoy call: returns B={value:#x}'+(' and stores it at M' if write else '')+f'; the wrapper removes {args} header arguments || '+' ; '.join(f'{i.mnemonic} {i.op_str}' for i in prev[-7:]+nxt[:3])
        elif (len(prev)>=3 and prev[-1].mnemonic=='mov' and prev[-1].op_str.startswith('ecx, 0x') and prev[-2].mnemonic=='lea' and prev[-2].op_str.startswith('ebx, [0x')
              and prev[-3].mnemonic=='mov' and prev[-3].op_str.startswith('eax, 0x')):
            kind='store';value=0;args=0
            evidence='register decoy: stores ecx at [ebx] || '+' ; '.join(f'{i.mnemonic} {i.op_str}' for i in prev[-6:]+nxt[:5])
        elif (len(prev)>=2 and prev[-1].mnemonic=='push' and prev[-2].mnemonic=='lea' and prev[-1].op_str==prev[-2].op_str.split(',')[0]
              and len(prev)>=3 and prev[-3].mnemonic=='push' and prev[-3].op_str=='4'
              and any(i.mnemonic=='cmp' and i.op_str.startswith('eax, 0x') for i in nxt[:3]) and any(i.mnemonic=='jle' for i in nxt[:5])):
            kind='bounded';value=0;args=2
            evidence='result compared, clean path when small: returns 0, removes (4, buffer) || '+' ; '.join(f'{i.mnemonic} {i.op_str}' for i in prev[-6:]+nxt[:5])
        elif resume_target(prev,site) is not None:
            target,args=resume_target(prev,site);kind='resume';value=target
            evidence=f'continues at esi={target:#x} with {args} stdcall arguments; falling through sets a penalty || '+' ; '.join(f'{i.mnemonic} {i.op_str}' for i in prev[-6:]+nxt[:3])
        else:
            kind='trigger';evidence=' ; '.join(f'{i.mnemonic} {i.op_str}' for i in prev[-6:])+' || '+' ; '.join(f'{i.mnemonic} {i.op_str}' for i in nxt[:3])
        sites.append({'site':hex(site),'return':hex(site+6),'kind':kind,'evidence':evidence,**({'value':hex(value)} if kind in ('integrity','resume','mirror','store','bounded') else {}),
                      **({'args':resume_target(prev,site)[1]} if kind=='resume' else {}),**({'args':args|(0x80 if write else 0)} if kind=='mirror' else {}),
                      **({'args':args} if kind in ('store','bounded') else {})})
    out=ROOT/'private/analysis/protection';out.mkdir(parents=True,exist_ok=True)
    (out/'redirects.json').write_text(json.dumps({'input_sha256':EXPECTED,'header_stub':hex(STUB),'header_table':table,'slot':hex(SLOT),'slot_sites':sites},indent=1)+'\n',encoding='utf-8')
    kinds={'get_last_error':'MH_REDIRECT_GET_LAST_ERROR','validate_pointer':'MH_REDIRECT_VALIDATE_POINTER','trigger':'MH_REDIRECT_TRIGGER','integrity':'MH_REDIRECT_INTEGRITY','resume':'MH_REDIRECT_RESUME','mirror':'MH_REDIRECT_MIRROR','store':'MH_REDIRECT_STORE','bounded':'MH_REDIRECT_INTEGRITY'}
    header=('/* Generated by tools/resolve_protection_redirects.py from the user\'s executable; private. */\n'
            f'static const mh_redirect_site mh_redirect_sites[{len(sites)}]={{\n'+
            ''.join(f'    {{{s["return"]}u,{kinds[s["kind"]]},{s.get("value","0x0")}u,{s.get("args",0)}}},\n' for s in sorted(sites,key=lambda s:int(s['return'],16)))+'};\n')
    (out/'redirect_sites.h').write_text(header,encoding='utf-8',newline='\n')
    count=lambda k:sum(1 for s in sites if s['kind']==k)
    print(f'header table: {len(table)} sites, all resolved to imports; slot sites: {len(sites)} =',
          {k:count(k) for k in kinds})
    for s in sites:
        if s['kind']!='trigger':print(' ',s['site'],s['kind'],'-',s['evidence'])
if __name__=='__main__':main()
