"""Lift a bounded multimedia-time candidate to private C, without execution."""
import hashlib,json,sys
from inspect_entrypoint import ROOT,GAME,PCRECOMP,EXPECTED,REVISION

def main():
    if (PCRECOMP/'REVISION.txt').read_text(encoding='ascii').strip()!=REVISION:raise SystemExit('unexpected PCRecomp revision')
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected game hash')
    for part in ('pe','disasm','lift'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from pe_analyze import analyze_pe,build_iat_map
    from disasm32 import Disassembler
    from lift32 import Lifter
    info=analyze_pe(str(GAME));iat=build_iat_map(info)
    function=Disassembler(data,info.image_base,info.sections).disassemble_function(0x6081a0,iat)
    if not function:raise SystemExit('candidate not recovered')
    insns=[ins for block in function.blocks.values() for ins in block.instructions]
    if not 1<=len(insns)<=1500:raise SystemExit('candidate exceeds instruction budget')
    if not any(i.address==0x6081af and i.is_call for i in insns):raise SystemExit('expected timer call not recovered')
    generated=Lifter(iat_map=iat).lift_function(function)
    out=ROOT/'private/analysis/candidate_time';out.mkdir(parents=True,exist_ok=True)
    (out/'candidate.c').write_text(generated+'\n',encoding='utf-8')
    report={'address':'0x6081a0','input_sha256':EXPECTED,'pcrecomp_revision':REVISION,
            'instruction_count':len(insns),'block_count':len(function.blocks),
            'direct_calls':[hex(x) for x in sorted(function.calls_to)],
            'source_sha256':hashlib.sha256(generated.encode('utf-8')).hexdigest(),
            'todo_markers':generated.count('RECOMP_TODO'),
            'limitations':['heuristic function boundary and reachability unproven','other calls unresolved','not compiled or executed']}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('candidate 0x6081a0:',len(insns),'instructions,',len(function.blocks),'blocks; generated C stays private')

if __name__=='__main__':main()
