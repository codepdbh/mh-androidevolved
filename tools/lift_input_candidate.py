"""Lift one candidate containing a DirectInput8Create thunk call; output private."""
import hashlib,json,sys
from inspect_entrypoint import ROOT,GAME,PCRECOMP,EXPECTED,REVISION

def main():
    if (PCRECOMP/'REVISION.txt').read_text(encoding='ascii').strip()!=REVISION:raise SystemExit('unexpected PCRecomp revision')
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    for part in ('pe','disasm','lift'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from pe_analyze import analyze_pe,build_iat_map
    from disasm32 import Disassembler
    from lift32 import Lifter
    info=analyze_pe(str(GAME));iat=build_iat_map(info);dis=Disassembler(data,info.image_base,info.sections)
    start=0x4c1ba0;expected_call=0x644098
    function=dis.disassemble_function(start,iat)
    if not function:raise SystemExit('candidate not recovered')
    insns=[ins for block in function.blocks.values() for ins in block.instructions]
    if not 1<=len(insns)<=1500:raise SystemExit('candidate instruction budget exceeded')
    if not any(i.is_call and i.get_branch_target()==expected_call for i in insns):raise SystemExit('expected input thunk call not recovered')
    code=Lifter(iat_map=iat).lift_function(function)
    out=ROOT/'private/analysis/candidate_input';out.mkdir(parents=True,exist_ok=True)
    (out/'candidate.c').write_text(code+'\n',encoding='utf-8')
    report={'pcrecomp_revision':REVISION,'input_sha256':EXPECTED,'address':hex(start),
            'instruction_count':len(insns),'block_count':len(function.blocks),
            'direct_calls':[hex(x) for x in sorted(function.calls_to)],
            'source_sha256':hashlib.sha256(code.encode('utf-8')).hexdigest(),
            'todo_markers':code.count('RECOMP_TODO'),
            'limitations':['heuristic boundary and reachability unproven','input and other calls unresolved','not compiled or executed']}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(f'candidate={start:#x}; blocks={len(function.blocks)}; instructions={len(insns)}; C private')
if __name__=='__main__':main()
