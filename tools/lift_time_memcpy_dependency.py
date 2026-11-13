"""Lift 0x481340 (two guarded buffer copies) and its callee 0x611640 to private C.

0x611640 is a self-contained cdecl copy routine (rep movsb/movsd). Both call
sites in 0x481340 are rewritten with their exact x86 return addresses.
"""
import hashlib,json,re,sys
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,PCRECOMP,EXPECTED,REVISION
SPECS={
 0x481340:[('cmp','dword ptr [esp + 4], 0'),('je','0x4813a4'),('cmp','dword ptr [0x71c860], 0'),('je','0x4813a4'),
           ('cmp','dword ptr [0x71c87c], 0'),('je','0x48137a'),('mov','ecx, dword ptr [0x71c87c]'),('mov','eax, ecx'),
           ('push','dword ptr [ecx + 0x1b8]'),('push','0x71a460'),('push','dword ptr [eax + 0x170]'),('call','0x611640'),
           ('add','esp, 0xc'),('cmp','dword ptr [0x71c880], 0'),('je','0x4813a4'),('mov','edx, dword ptr [0x71c880]'),
           ('mov','ecx, edx'),('push','dword ptr [edx + 0x1b8]'),('push','0x71a860'),('push','dword ptr [ecx + 0x170]'),
           ('call','0x611640'),('add','esp, 0xc'),('ret','')],
 0x611640:[('push','esi'),('push','edi'),('mov','edx, dword ptr [esp + 0xc]'),('mov','eax, dword ptr [esp + 0x14]'),
           ('mov','esi, dword ptr [esp + 0x10]'),('mov','edi, edx'),('xor','ecx, ecx'),('cmp','eax, 0x10'),('jl','0x611670'),
           ('sub','ecx, edi'),('and','ecx, 3'),('je','0x611662'),('sub','eax, ecx'),('rep movsb','byte ptr es:[edi], byte ptr [esi]'),
           ('mov','ecx, eax'),('and','eax, 3'),('shr','ecx, 2'),('rep movsd','dword ptr es:[edi], dword ptr [esi]'),
           ('test','eax, eax'),('je','0x611674'),('mov','ecx, eax'),('rep movsb','byte ptr es:[edi], byte ptr [esi]'),
           ('mov','eax, edx'),('pop','edi'),('pop','esi'),('ret','')]}
SITES={0x481372:0x611640,0x48139c:0x611640}
ALLOWED={'MEM8','MEM32','PUSH32','POP32_VAL','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT'}
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    if (PCRECOMP/'REVISION.txt').read_text(encoding='ascii').strip()!=REVISION:raise SystemExit('unexpected tool revision')
    pe=pefile.PE(data=data,fast_load=True);decoder=Cs(CS_ARCH_X86,CS_MODE_32);extents={}
    for address,expected in SPECS.items():
        ins=[];code=pe.get_data(address-pe.OPTIONAL_HEADER.ImageBase,0x80)
        for i in decoder.disasm(code,address):
            ins.append(i)
            if len(ins)==len(expected):break
        if [(i.mnemonic,i.op_str) for i in ins]!=expected:raise SystemExit(f'unexpected instructions at {address:#x}')
        extents[address]=code[:sum(i.size for i in ins)]
    for part in ('pe','disasm','lift'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from pe_analyze import analyze_pe,build_iat_map
    from disasm32 import Disassembler
    from lift32 import Lifter
    info=analyze_pe(str(GAME));iat=build_iat_map(info);dis=Disassembler(data,info.image_base,info.sections)
    out=ROOT/'private/analysis/candidate_time/dependencies';out.mkdir(parents=True,exist_ok=True);items=[]
    for address,expected in SPECS.items():
        func=dis.disassemble_function(address,iat)
        if not func or sum(len(b.instructions) for b in func.blocks.values())!=len(expected):raise SystemExit(f'unexpected extent at {address:#x}')
        if set(func.calls_to)!=({0x611640} if address==0x481340 else set()):raise SystemExit(f'unexpected calls at {address:#x}')
        source=Lifter(iat_map=iat).lift_function(func)
        if 'RECOMP_TODO' in source:raise SystemExit(f'unsupported instruction at {address:#x}')
        lifted=hashlib.sha256(source.encode()).hexdigest();header=''
        if address==0x481340:
            for site,target in SITES.items():
                pattern=rf'RECOMP_CALL\(sub_{target:08X}\); /\* 0x{site:08X}: call 0x{target:x} \*/'
                source,n=re.subn(pattern,f'MH_RECOMP_CALL_AT(sub_{target:08X}, 0x{site+5:08X}u);',source)
                if n!=1:raise SystemExit('call replacement mismatch')
            header='void sub_00611640(void);\n'
        else:
            # Route every string copy through the bounds-checked adapter helper.
            source,n=re.subn(r'\brecomp_rep_movs\(','mh_recomp_rep_movs(',source)
            if n!=3:raise SystemExit('unexpected rep movs count')
        helpers=set(re.findall(r'\b(recomp_\w+)\s*\(',source))
        if not helpers.issubset({'recomp_flags_pack'}):raise SystemExit(f'unchecked runtime helpers at {address:#x}: '+','.join(sorted(helpers)))
        operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',source))
        if not operations.issubset(ALLOWED):raise SystemExit(f'unsupported operations at {address:#x}: '+','.join(sorted(operations-ALLOWED)))
        name=f'dep_{address:08x}_precise.c';text=header+source
        (out/name).write_text(text+'\n',encoding='utf-8')
        items.append({'address':hex(address),'source':name,'instructions':len(expected),'bytes_sha256':hashlib.sha256(extents[address]).hexdigest(),
                      'bytes_length':len(extents[address]),'lifted_sha256':lifted,'adapted_sha256':hashlib.sha256(text.encode()).hexdigest(),'operations':sorted(operations)})
    (out/'memcpy_report.json').write_text(json.dumps({'input_sha256':EXPECTED,'items':items,
        'sites':[{'call':hex(a),'return':hex(a+5)} for a in sorted(SITES)],
        'limitations':['direction flag assumed clear','reachability unproved','not integrated into game']},indent=2)+'\n',encoding='utf-8')
    print('translated 0x481340 and 0x611640; sources remain private')
if __name__=='__main__':main()
