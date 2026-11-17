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
   - trigger: anything else (anti-tamper checks with magic register values). These
     stay fail-closed until each is analysed.
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
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    pe=pefile.PE(data=data);base=pe.OPTIONAL_HEADER.ImageBase
    if data[STUB-base:STUB-base+len(STUB_BYTES)]!=STUB_BYTES:raise SystemExit('header stub differs from the analysed one')
    iat={imp.address:(e.dll.decode().lower(),imp.name.decode() if imp.name else f'ordinal_{imp.ordinal}') for e in pe.DIRECTORY_ENTRY_IMPORT for imp in e.imports}
    text=pe.get_data(0x1000,0x26d200);md=Cs(CS_ARCH_X86,CS_MODE_32)
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
        else:
            kind='trigger';evidence=' ; '.join(f'{i.mnemonic} {i.op_str}' for i in prev[-6:])+' || '+' ; '.join(f'{i.mnemonic} {i.op_str}' for i in nxt[:3])
        sites.append({'site':hex(site),'return':hex(site+6),'kind':kind,'evidence':evidence})
    out=ROOT/'private/analysis/protection';out.mkdir(parents=True,exist_ok=True)
    (out/'redirects.json').write_text(json.dumps({'input_sha256':EXPECTED,'header_stub':hex(STUB),'header_table':table,'slot':hex(SLOT),'slot_sites':sites},indent=1)+'\n',encoding='utf-8')
    kinds={'get_last_error':'MH_REDIRECT_GET_LAST_ERROR','validate_pointer':'MH_REDIRECT_VALIDATE_POINTER','trigger':'MH_REDIRECT_TRIGGER'}
    header=('/* Generated by tools/resolve_protection_redirects.py from the user\'s executable; private. */\n'
            f'static const mh_redirect_site mh_redirect_sites[{len(sites)}]={{\n'+
            ''.join(f'    {{{s["return"]}u,{kinds[s["kind"]]}}},\n' for s in sorted(sites,key=lambda s:int(s['return'],16)))+'};\n')
    (out/'redirect_sites.h').write_text(header,encoding='utf-8',newline='\n')
    count=lambda k:sum(1 for s in sites if s['kind']==k)
    print(f'header table: {len(table)} sites, all resolved to imports; slot sites: {len(sites)} =',
          {k:count(k) for k in kinds})
    for s in sites:
        if s['kind']!='trigger':print(' ',s['site'],s['kind'],'-',s['evidence'])
if __name__=='__main__':main()
