"""Validate two call sites and adapt one private structure-copy dependency."""
import hashlib,json,re
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,EXPECTED
def main():
    folder=ROOT/'private/analysis/candidate_time/dependencies';report=json.loads((folder/'copy_report.json').read_text())
    source=(folder/'dep_00604d20.c').read_text(encoding='utf-8').removesuffix('\n')
    if report['address']!='0x604d20' or hashlib.sha256(source.encode()).hexdigest()!=report['source_sha256']:raise SystemExit('copy candidate hash mismatch')
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    pe=pefile.PE(data=data);decoder=Cs(CS_ARCH_X86,CS_MODE_32)
    sites={0x604d89:0x604dc0,0x604d97:0x604f30}
    for address,target in sites.items():
        ins=list(decoder.disasm(pe.get_data(address-pe.OPTIONAL_HEADER.ImageBase,5),address,count=1))
        if len(ins)!=1 or ins[0].mnemonic!='call' or ins[0].size!=5 or int(ins[0].op_str,16)!=target:raise SystemExit('copy call decoding mismatch')
        pattern=rf'RECOMP_CALL\(sub_{target:08X}\); /\* 0x{address:08X}: call 0x{target:x} \*/'
        source,n=re.subn(pattern,f'MH_RECOMP_CALL_AT(sub_{target:08X}, 0x{address+5:08X}u);',source)
        if n!=1:raise SystemExit('copy call replacement mismatch')
    (folder/'dep_00604d20_precise.c').write_text(source+'\n',encoding='utf-8')
    (folder/'copy_precise_report.json').write_text(json.dumps({'source_sha256':report['source_sha256'],'adapted_sha256':hashlib.sha256(source.encode()).hexdigest(),
        'sites':[{'call':hex(a),'return':hex(a+5)} for a in sorted(sites)],'limitations':['other calls unresolved','not whole-game tested']},indent=2)+'\n',encoding='utf-8')
    print('adapted 2 verified direct call sites; source remains private')
if __name__=='__main__':main()
