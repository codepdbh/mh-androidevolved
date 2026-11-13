"""Prepare a narrow, validated return-address adaptation of one private candidate."""
import hashlib,json,re
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,EXPECTED

def main():
    folder=ROOT/'private/analysis/candidate_time';report=json.loads((folder/'report.json').read_text())
    source=(folder/'candidate.c').read_text(encoding='utf-8').removesuffix('\n')
    if report['address']!='0x6081a0' or hashlib.sha256(source.encode()).hexdigest()!=report['source_sha256']:raise SystemExit('candidate hash or address mismatch')
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    pe=pefile.PE(data=data);decoder=Cs(CS_ARCH_X86,CS_MODE_32)
    sites={0x6081a8:5,0x6081af:6,0x60820c:5,0x608213:6,0x608221:5,0x60825c:5,
           0x6082a0:5,0x6082a8:5,0x608395:5,0x6083a4:5,0x6083a9:5}
    pattern=re.compile(r'(RECOMP_(?:I)?CALL)\((.*?)\); /\* 0x([0-9A-Fa-f]{8}): call ([^*]+) \*/')
    matches=list(pattern.finditer(source));seen=set()
    if len(matches)!=len(sites):raise SystemExit('unexpected call count')
    for match in reversed(matches):
        op,arg,address=match.group(1),match.group(2),int(match.group(3),16)
        if address not in sites or address in seen:raise SystemExit('unexpected or duplicate call site')
        decoded=list(decoder.disasm(pe.get_data(address-pe.OPTIONAL_HEADER.ImageBase,6),address,count=1))
        if len(decoded)!=1 or decoded[0].mnemonic!='call' or decoded[0].size!=sites[address]:raise SystemExit('call decoding mismatch')
        if (op=='RECOMP_ICALL')!=(sites[address]==6):raise SystemExit('call kind mismatch')
        if decoded[0].op_str.lower()!=match.group(4).strip().lower():raise SystemExit('call target text mismatch')
        if op=='RECOMP_CALL' and arg.lower()!=f'sub_{int(decoded[0].op_str,16):08x}':raise SystemExit('direct target mismatch')
        if op=='RECOMP_ICALL' and (arg!='MEM32(0x81B4FC)' or decoded[0].op_str.lower()!='dword ptr [0x81b4fc]'):raise SystemExit('indirect IAT target mismatch')
        replacement=('MH_RECOMP_ICALL_AT' if op=='RECOMP_ICALL' else 'MH_RECOMP_CALL_AT')+f'({arg}, 0x{address+sites[address]:08X}u);'
        source=source[:match.start()]+replacement+source[match.end():];seen.add(address)
    if seen!=set(sites):raise SystemExit('missing call site')
    (folder/'candidate_precise.c').write_text(source+'\n',encoding='utf-8')
    (folder/'precise_report.json').write_text(json.dumps({'original_sha256':report['source_sha256'],'adapted_sha256':hashlib.sha256(source.encode()).hexdigest(),
        'sites':[{'call':hex(a),'return':hex(a+n)} for a,n in sorted(sites.items())],
        'limitations':['static call decoding only','no proof of function reachability or equivalence','not executed']},indent=2)+'\n',encoding='utf-8')
    print('validated',len(sites),'call lengths; adapted C remains private')
if __name__=='__main__':main()
