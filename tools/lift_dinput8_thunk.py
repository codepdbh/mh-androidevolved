"""Inspect and lift the DirectInput8Create import-thunk candidate."""
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
    address=0x644098;slot=0x81b35c
    if iat.get(slot,('',''))[1]!='DirectInput8Create':raise SystemExit('import slot mismatch')
    function=dis.disassemble_function(address,iat)
    if not function:raise SystemExit('thunk not recovered')
    insns=[i for b in function.blocks.values() for i in b.instructions]
    if len(insns)!=1 or insns[0].mnemonic!='jmp' or insns[0].size!=6:raise SystemExit('unexpected thunk shape')
    code=Lifter(iat_map=iat).lift_function(function)
    out=ROOT/'private/analysis/dinput8_thunk';out.mkdir(parents=True,exist_ok=True)
    (out/'candidate.c').write_text(code+'\n',encoding='utf-8')
    report={'input_sha256':EXPECTED,'pcrecomp_revision':REVISION,'address':hex(address),'slot':hex(slot),
            'import':'dinput8.dll!DirectInput8Create','source_sha256':hashlib.sha256(code.encode('utf-8')).hexdigest(),
            'limitations':['not linked to a DirectInput implementation','not compiled or executed','boundary and reachability unproven']}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('One DirectInput8Create import-thunk candidate lifted; runtime binding remains unresolved')
if __name__=='__main__':main()
