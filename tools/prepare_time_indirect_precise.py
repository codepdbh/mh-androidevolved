"""Validate six fixed call sites and adapt one private indirect dependency."""
import hashlib,json,re
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,EXPECTED
def main():
    folder=ROOT/'private/analysis/candidate_time/dependencies';report=json.loads((folder/'indirect_report.json').read_text())
    source=(folder/'dep_00604dc0.c').read_text(encoding='utf-8').removesuffix('\n')
    if report['address']!='0x604dc0' or hashlib.sha256(source.encode()).hexdigest()!=report['source_sha256']:raise SystemExit('indirect candidate hash mismatch')
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    pe=pefile.PE(data=data);decoder=Cs(CS_ARCH_X86,CS_MODE_32)
    sites={0x604dd3:(3,'dword ptr [ebx + 0x28]'),0x604deb:(5,'0x401030'),0x604e0a:(5,'0x401030'),
           0x604e1f:(5,'0x4932f0'),0x604e29:(5,'0x493230'),0x604e3d:(3,'dword ptr [ebx + 0x24]')}
    pattern=re.compile(r'(RECOMP_(?:I)?CALL)\((.*?)\); /\* 0x([0-9A-Fa-f]{8}): call ([^*]+) \*/')
    matches=list(pattern.finditer(source));seen=set()
    if len(matches)!=len(sites):raise SystemExit('unexpected indirect candidate call count')
    for match in reversed(matches):
        op,arg,address=match.group(1),match.group(2),int(match.group(3),16)
        if address not in sites or address in seen:raise SystemExit('unexpected call site')
        size,target=sites[address];ins=list(decoder.disasm(pe.get_data(address-pe.OPTIONAL_HEADER.ImageBase,6),address,count=1))
        if len(ins)!=1 or ins[0].mnemonic!='call' or ins[0].size!=size or ins[0].op_str.lower()!=target:raise SystemExit('call decoding mismatch')
        if match.group(4).strip().lower()!=target or (op=='RECOMP_ICALL')!=(size==3):raise SystemExit('call kind or target mismatch')
        if size==5 and arg.lower()!=f'sub_{int(target,16):08x}':raise SystemExit('direct call argument mismatch')
        if size==3 and arg.lower()!=('mem32(ebx + 0x28)' if address==0x604dd3 else 'mem32(ebx + 0x24)'):raise SystemExit('indirect argument mismatch')
        replacement=('MH_RECOMP_ICALL_AT' if size==3 else 'MH_RECOMP_CALL_AT')+f'({arg}, 0x{address+size:08X}u);'
        source=source[:match.start()]+replacement+source[match.end():];seen.add(address)
    (folder/'dep_00604dc0_precise.c').write_text(source+'\n',encoding='utf-8')
    (folder/'indirect_precise_report.json').write_text(json.dumps({'source_sha256':report['source_sha256'],'adapted_sha256':hashlib.sha256(source.encode()).hexdigest(),
        'sites':[{'call':hex(a),'return':hex(a+n)} for a,(n,_) in sorted(sites.items())],
        'limitations':['indirect targets and direct dependencies unresolved','not tested or linked to game']},indent=2)+'\n',encoding='utf-8')
    print('adapted',len(sites),'verified call sites; source remains private')
if __name__=='__main__':main()
