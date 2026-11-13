"""Lift a verified three-instruction structure setter to private C."""
import hashlib,json,sys
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,PCRECOMP,EXPECTED,REVISION
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    if (PCRECOMP/'REVISION.txt').read_text(encoding='ascii').strip()!=REVISION:raise SystemExit('unexpected tool revision')
    pe=pefile.PE(data=data);address=0x604f30;decoder=Cs(CS_ARCH_X86,CS_MODE_32)
    ins=list(decoder.disasm(pe.get_data(address-pe.OPTIONAL_HEADER.ImageBase,16),address,count=3))
    if [(i.mnemonic,i.op_str) for i in ins]!=[('mov','eax, dword ptr [esp + 4]'),('mov','dword ptr [ecx + 8], eax'),('ret','4')]:raise SystemExit('unexpected setter instructions')
    for part in ('pe','disasm','lift'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from pe_analyze import analyze_pe,build_iat_map
    from disasm32 import Disassembler
    from lift32 import Lifter
    info=analyze_pe(str(GAME));iat=build_iat_map(info);func=Disassembler(data,info.image_base,info.sections).disassemble_function(address,iat)
    if not func or sum(len(b.instructions) for b in func.blocks.values())!=3 or func.calls_to:raise SystemExit('unexpected setter extent')
    source=Lifter(iat_map=iat).lift_function(func)
    if 'RECOMP_TODO' in source:raise SystemExit('unsupported instruction')
    out=ROOT/'private/analysis/candidate_time/dependencies';out.mkdir(parents=True,exist_ok=True)
    (out/'dep_00604f30.c').write_text(source+'\n',encoding='utf-8')
    (out/'inner_report.json').write_text(json.dumps({'address':hex(address),'input_sha256':EXPECTED,'source_sha256':hashlib.sha256(source.encode()).hexdigest(),
        'instructions':3,'limitations':['reachability unproved','not integrated into game']},indent=2)+'\n',encoding='utf-8')
    print('translated verified three-instruction setter; source remains private')
if __name__=='__main__':main()
