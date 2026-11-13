"""Lift one bounded structure-copy candidate to a private file."""
import hashlib,json,sys
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,PCRECOMP,EXPECTED,REVISION
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    if (PCRECOMP/'REVISION.txt').read_text(encoding='ascii').strip()!=REVISION:raise SystemExit('unexpected tool revision')
    pe=pefile.PE(data=data);decoder=Cs(CS_ARCH_X86,CS_MODE_32);address=0x604d20
    ins=list(decoder.disasm(pe.get_data(address-pe.OPTIONAL_HEADER.ImageBase,16),address,count=4))
    if [(i.mnemonic,i.op_str) for i in ins]!=[('push','ebx'),('mov','ebx, ecx'),('mov','eax, dword ptr [esp + 8]'),('xor','ecx, ecx')]:raise SystemExit('unexpected copy candidate prologue')
    for part in ('pe','disasm','lift'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from pe_analyze import analyze_pe,build_iat_map
    from disasm32 import Disassembler
    from lift32 import Lifter
    info=analyze_pe(str(GAME));iat=build_iat_map(info);func=Disassembler(data,info.image_base,info.sections).disassemble_function(address,iat)
    if not func:raise SystemExit('copy candidate not recovered')
    instructions=[i for block in func.blocks.values() for i in block.instructions]
    if not 1<=len(instructions)<=600 or set(func.calls_to)!={0x604dc0,0x604f30}:raise SystemExit(f'copy candidate extent or dependencies unexpected: {len(instructions)} instructions, calls {[hex(x) for x in sorted(func.calls_to)]}')
    source=Lifter(iat_map=iat).lift_function(func)
    if 'RECOMP_TODO' in source:raise SystemExit('unsupported instruction')
    out=ROOT/'private/analysis/candidate_time/dependencies';out.mkdir(parents=True,exist_ok=True)
    (out/'dep_00604d20.c').write_text(source+'\n',encoding='utf-8')
    (out/'copy_report.json').write_text(json.dumps({'address':hex(address),'input_sha256':EXPECTED,'pcrecomp_revision':REVISION,
        'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'instructions':len(instructions),'blocks':len(func.blocks),'direct_calls':[hex(x) for x in sorted(func.calls_to)],
        'limitations':['heuristic boundary and reachability unproved','not integrated or executed']},indent=2)+'\n',encoding='utf-8')
    print('copy candidate:',len(instructions),'instructions,',len(func.blocks),'blocks; C remains private')
if __name__=='__main__':main()
