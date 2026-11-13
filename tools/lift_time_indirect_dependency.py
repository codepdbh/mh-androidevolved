"""Lift one bounded dependency containing an indirect call; no execution."""
import hashlib,json,sys
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,PCRECOMP,EXPECTED,REVISION
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    if (PCRECOMP/'REVISION.txt').read_text(encoding='ascii').strip()!=REVISION:raise SystemExit('unexpected tool revision')
    pe=pefile.PE(data=data);address=0x604dc0;decoder=Cs(CS_ARCH_X86,CS_MODE_32)
    ins=list(decoder.disasm(pe.get_data(address-pe.OPTIONAL_HEADER.ImageBase,16),address,count=3))
    if [(i.mnemonic,i.op_str) for i in ins]!=[('push','ebx'),('mov','eax, dword ptr [esp + 8]'),('mov','dword ptr [ecx + 0x10], eax')]:raise SystemExit('unexpected indirect candidate prologue')
    for part in ('pe','disasm','lift'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from pe_analyze import analyze_pe,build_iat_map
    from disasm32 import Disassembler
    from lift32 import Lifter
    info=analyze_pe(str(GAME));iat=build_iat_map(info);func=Disassembler(data,info.image_base,info.sections).disassemble_function(address,iat)
    if not func:raise SystemExit('indirect candidate missing')
    instructions=[i for b in func.blocks.values() for i in b.instructions]
    if not 1<=len(instructions)<=1000:raise SystemExit('candidate exceeds instruction budget')
    if not any(i.address==0x604dd3 and i.is_call for i in instructions):raise SystemExit('expected indirect call missing')
    source=Lifter(iat_map=iat).lift_function(func)
    out=ROOT/'private/analysis/candidate_time/dependencies';out.mkdir(parents=True,exist_ok=True)
    (out/'dep_00604dc0.c').write_text(source+'\n',encoding='utf-8')
    (out/'indirect_report.json').write_text(json.dumps({'address':hex(address),'input_sha256':EXPECTED,'source_sha256':hashlib.sha256(source.encode()).hexdigest(),
        'instructions':len(instructions),'blocks':len(func.blocks),'direct_calls':[hex(x) for x in sorted(func.calls_to)],'todo_markers':source.count('RECOMP_TODO'),
        'limitations':['static candidate; boundaries and reachability unproved','indirect calls unresolved','not compiled or executed']},indent=2)+'\n',encoding='utf-8')
    print('indirect candidate:',len(instructions),'instructions,',len(func.blocks),'blocks; generated C remains private')
if __name__=='__main__':main()
