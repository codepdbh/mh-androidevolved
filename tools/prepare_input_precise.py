"""Adapt three audited DirectInput candidate call sites to preserve x86 return VAs."""
import hashlib,json,sys
from inspect_entrypoint import ROOT,GAME,PCRECOMP,EXPECTED,REVISION

def main():
    if (PCRECOMP/'REVISION.txt').read_text(encoding='ascii').strip()!=REVISION:raise SystemExit('unexpected PCRecomp revision')
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    base=ROOT/'private/analysis/candidate_input';report=json.loads((base/'report.json').read_text(encoding='utf-8'))
    source=(base/'candidate.c').read_text(encoding='utf-8').removesuffix('\n');digest=hashlib.sha256(source.encode('utf-8')).hexdigest()
    if report['address']!='0x4c1ba0' or digest!=report['source_sha256']:raise SystemExit('unexpected candidate')
    for part in ('pe','disasm'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from pe_analyze import analyze_pe,build_iat_map
    from disasm32 import Disassembler
    info=analyze_pe(str(GAME));dis=Disassembler(data,info.image_base,info.sections)
    function=dis.disassemble_function(0x4c1ba0,build_iat_map(info))
    if not function:raise SystemExit('candidate not recovered')
    instructions={i.address:i for b in function.blocks.values() for i in b.instructions}
    sites=[(0x4c1bc2,'RECOMP_ICALL(MEM32(0x81B3AC));','MH_RECOMP_ICALL_AT(MEM32(0x81B3AC), {ret});'),
           (0x4c1bc9,'RECOMP_CALL(sub_00644098);','MH_RECOMP_CALL_AT(sub_00644098, {ret});'),
           (0x4c1bde,'RECOMP_CALL(sub_0060F110);','MH_RECOMP_CALL_AT(sub_0060F110, {ret});')]
    adapted=source;metadata=[]
    for addr,old,template in sites:
        ins=instructions.get(addr)
        if not ins or not ins.is_call or adapted.count(old)!=1:raise SystemExit(f'unexpected call at {addr:#x}')
        ret=addr+ins.size;adapted=adapted.replace(old,template.format(ret=f'0x{ret:08X}u'))
        metadata.append({'call':hex(addr),'size':ins.size,'return':hex(ret)})
    if 'RECOMP_ICALL(' in adapted or 'RECOMP_CALL(' in adapted:raise SystemExit('unadapted calls remain')
    (base/'candidate_precise.c').write_text(adapted+'\n',encoding='utf-8')
    (base/'precise_report.json').write_text(json.dumps({'original_sha256':digest,'adapted_sha256':hashlib.sha256(adapted.encode('utf-8')).hexdigest(),
        'call_sites':metadata,'limitations':['specific candidate only','not integrated into PCRecomp generally']},indent=2)+'\n',encoding='utf-8')
    print(f'{len(sites)} call sites adapted using original instruction lengths')
if __name__=='__main__':main()
