"""Lift the aligned stack probe 0x648540 (tail-jumps into 0x648500) to private C.

The probe rounds EAX up to four bytes, touches each 4 KiB page below the
caller's stack, moves ESP down, restores EDX and returns with EAX = new ESP.
"""
import hashlib,json,re,sys
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,PCRECOMP,EXPECTED,REVISION
REGIONS={
 0x648540:[('add','eax, 3'),('and','eax, 0xfffffffc'),('jmp','0x648500')],
 0x648500:[('push','edx'),('lea','edx, [esp + 8]'),('cmp','eax, 0x1000'),('jb','0x648520'),('sub','edx, 0x1000'),
           ('or','dword ptr [edx], 0'),('sub','eax, 0x1000'),('jmp','0x648505'),('lea','eax, [eax]'),('sub','edx, eax'),('mov','eax, esp'),
           ('mov','esp, edx'),('mov','edx, dword ptr [eax]'),('or','dword ptr [esp], 0'),('push','dword ptr [eax + 4]'),
           ('lea','eax, [esp + 4]'),('ret','')]}
# 0x64851c 'lea eax,[eax]' is alignment padding after the loop jump; it is unreachable and not lifted.
ALLOWED={'MEM32','PUSH32','RECOMP_ENTER','RECOMP_FLAGS_OUT'}
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    if (PCRECOMP/'REVISION.txt').read_text(encoding='ascii').strip()!=REVISION:raise SystemExit('unexpected tool revision')
    pe=pefile.PE(data=data,fast_load=True);decoder=Cs(CS_ARCH_X86,CS_MODE_32);regions=[]
    for address,expected in REGIONS.items():
        code=pe.get_data(address-pe.OPTIONAL_HEADER.ImageBase,0x40);ins=[]
        for i in decoder.disasm(code,address):
            ins.append(i)
            if len(ins)==len(expected):break
        if [(i.mnemonic,i.op_str) for i in ins]!=expected:raise SystemExit(f'unexpected instructions at {address:#x}')
        length=sum(i.size for i in ins)
        regions.append({'address':hex(address),'length':length,'bytes_sha256':hashlib.sha256(code[:length]).hexdigest()})
    for part in ('pe','disasm','lift'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from pe_analyze import analyze_pe,build_iat_map
    from disasm32 import Disassembler
    from lift32 import Lifter
    info=analyze_pe(str(GAME));iat=build_iat_map(info)
    func=Disassembler(data,info.image_base,info.sections).disassemble_function(0x648540,iat)
    if not func or sum(len(b.instructions) for b in func.blocks.values())!=19 or func.calls_to:raise SystemExit('unexpected probe extent')
    source=Lifter(iat_map=iat).lift_function(func)
    if 'RECOMP_TODO' in source:raise SystemExit('unsupported instruction')
    helpers=set(re.findall(r'\b(recomp_\w+)\s*\(',source))
    if helpers:raise SystemExit('unchecked runtime helpers: '+','.join(sorted(helpers)))
    operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',source))
    if not operations.issubset(ALLOWED):raise SystemExit('unsupported probe operations: '+','.join(sorted(operations-ALLOWED)))
    out=ROOT/'private/analysis/candidate_time/dependencies';out.mkdir(parents=True,exist_ok=True)
    (out/'dep_00648540.c').write_text(source+'\n',encoding='utf-8')
    (out/'stack_probe_report.json').write_text(json.dumps({'address':'0x648540','input_sha256':EXPECTED,'regions':regions,'instructions':19,
        'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'operations':sorted(operations),
        'limitations':['guard pages not modelled; probes are plain checked accesses','reachability unproved','not integrated into game']},indent=2)+'\n',encoding='utf-8')
    print('translated verified stack probe; source remains private')
if __name__=='__main__':main()
