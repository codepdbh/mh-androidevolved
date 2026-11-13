"""Lift the verified nine-instruction mode dispatcher 0x5daa20 to private C.

Both direct calls are rewritten with their exact x86 return addresses. The
callees (0x476a80, 0x476aa0) stay unresolved and are test doubles in harnesses.
"""
import hashlib,json,re,sys
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,PCRECOMP,EXPECTED,REVISION
ADDRESS=0x5daa20;LENGTH=0x21
EXPECTED_INSTRUCTIONS=[('cmp','dword ptr [0x7d6b18], 0'),('jne','0x5daa30'),('call','0x476a80'),('mov','eax, eax'),
    ('cmp','dword ptr [0x7d6b18], 1'),('jne','0x5daa40'),('call','0x476aa0'),('mov','eax, eax'),('ret','')]
SITES={0x5daa29:0x476a80,0x5daa39:0x476aa0}
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    if (PCRECOMP/'REVISION.txt').read_text(encoding='ascii').strip()!=REVISION:raise SystemExit('unexpected tool revision')
    pe=pefile.PE(data=data,fast_load=True);code=pe.get_data(ADDRESS-pe.OPTIONAL_HEADER.ImageBase,LENGTH)
    ins=list(Cs(CS_ARCH_X86,CS_MODE_32).disasm(code,ADDRESS))
    if [(i.mnemonic,i.op_str) for i in ins]!=EXPECTED_INSTRUCTIONS or sum(i.size for i in ins)!=LENGTH:raise SystemExit('unexpected dispatcher instructions')
    for part in ('pe','disasm','lift'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from pe_analyze import analyze_pe,build_iat_map
    from disasm32 import Disassembler
    from lift32 import Lifter
    info=analyze_pe(str(GAME));iat=build_iat_map(info);func=Disassembler(data,info.image_base,info.sections).disassemble_function(ADDRESS,iat)
    if not func or sum(len(b.instructions) for b in func.blocks.values())!=9 or set(func.calls_to)!=set(SITES.values()):raise SystemExit('unexpected dispatcher extent')
    source=Lifter(iat_map=iat).lift_function(func)
    if 'RECOMP_TODO' in source:raise SystemExit('unsupported instruction')
    lifted_sha=hashlib.sha256(source.encode()).hexdigest()
    for address,target in SITES.items():
        pattern=rf'RECOMP_CALL\(sub_{target:08X}\); /\* 0x{address:08X}: call 0x{target:x} \*/'
        source,n=re.subn(pattern,f'MH_RECOMP_CALL_AT(sub_{target:08X}, 0x{address+5:08X}u);',source)
        if n!=1:raise SystemExit('dispatcher call replacement mismatch')
    operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',source))
    if not operations.issubset({'MEM32','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT'}):raise SystemExit('unsupported dispatcher operations: '+','.join(sorted(operations)))
    out=ROOT/'private/analysis/candidate_time/dependencies';out.mkdir(parents=True,exist_ok=True)
    header='void sub_00476A80(void);\nvoid sub_00476AA0(void);\n'
    (out/'dep_005daa20_precise.c').write_text(header+source+'\n',encoding='utf-8')
    (out/'branch_report.json').write_text(json.dumps({'address':hex(ADDRESS),'input_sha256':EXPECTED,'bytes_sha256':hashlib.sha256(code).hexdigest(),
        'lifted_sha256':lifted_sha,'adapted_sha256':hashlib.sha256((header+source).encode()).hexdigest(),'instructions':9,
        'sites':[{'call':hex(a),'return':hex(a+5)} for a in sorted(SITES)],
        'limitations':['callees are test doubles','reachability unproved','not integrated into game']},indent=2)+'\n',encoding='utf-8')
    print('translated verified nine-instruction dispatcher; source remains private')
if __name__=='__main__':main()
