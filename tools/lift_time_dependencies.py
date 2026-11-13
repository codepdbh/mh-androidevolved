"""Lift three statically checked tiny dependencies; output stays private."""
import hashlib,json,sys
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,PCRECOMP,EXPECTED,REVISION

def main():
    if (PCRECOMP/'REVISION.txt').read_text(encoding='ascii').strip()!=REVISION:raise SystemExit('unexpected PCRecomp revision')
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    pe=pefile.PE(data=data);decoder=Cs(CS_ARCH_X86,CS_MODE_32)
    expected={0x426ef0:[('ret','')],0x608410:[('ret','4')],
              0x481330:[('mov','eax, dword ptr [esp + 4]'),('mov','dword ptr [0x71c860], eax'),('ret','')]}
    for address,expected_ins in expected.items():
        got=list(decoder.disasm(pe.get_data(address-pe.OPTIONAL_HEADER.ImageBase,16),address,count=len(expected_ins)))
        if [(x.mnemonic,x.op_str) for x in got]!=expected_ins:raise SystemExit('dependency instruction mismatch')
    for part in ('pe','disasm','lift'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from pe_analyze import analyze_pe,build_iat_map
    from disasm32 import Disassembler
    from lift32 import Lifter
    info=analyze_pe(str(GAME));iat=build_iat_map(info);dis=Disassembler(data,info.image_base,info.sections)
    out=ROOT/'private/analysis/candidate_time/dependencies';out.mkdir(parents=True,exist_ok=True);items=[]
    for address,expected_ins in expected.items():
        function=dis.disassemble_function(address,iat)
        if not function:raise SystemExit('dependency not recovered')
        ins=[i for block in function.blocks.values() for i in block.instructions]
        if len(ins)!=len(expected_ins) or function.calls_to:raise SystemExit('unexpected dependency extent')
        code=Lifter(iat_map=iat).lift_function(function)
        if 'RECOMP_TODO' in code:raise SystemExit('unsupported instruction')
        name=f'dep_{address:08x}.c';(out/name).write_text(code+'\n',encoding='utf-8')
        items.append({'address':hex(address),'source':name,'sha256':hashlib.sha256(code.encode()).hexdigest(),'instructions':len(ins)})
    (out/'report.json').write_text(json.dumps({'input_sha256':EXPECTED,'pcrecomp_revision':REVISION,'items':items,
        'limitations':['static boundaries and reachability not proved','not tested or linked to game']},indent=2)+'\n',encoding='utf-8')
    print('lifted',len(items),'tiny dependencies; generated sources remain private')
if __name__=='__main__':main()
