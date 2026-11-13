"""Inspect bounded candidate instruction streams around timeGetTime references."""
import hashlib,json
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,EXPECTED

def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    pe=pefile.PE(data=data);section=next(s for s in pe.sections if s.Name.rstrip(b'\0')==b'.text')
    base=pe.OPTIONAL_HEADER.ImageBase+section.VirtualAddress;code=section.get_data()
    targets=(0x4c0c83,0x4c0f75,0x6067d8,0x6081af,0x608213,0x60f925,0x60fa20)
    decoder=Cs(CS_ARCH_X86,CS_MODE_32);reports=[]
    for target in targets:
        found=[]
        for start in range(target-512,target+1):
            off=start-base
            if off<=0 or not(code[off:off+3]==b'\x55\x8b\xec' or code[off-1] in (0xc3,0xcc)):continue
            instructions=list(decoder.disasm(code[off:off+min(target-start+40,768)],start))
            if any(i.mnemonic.startswith('ret') and i.address<target for i in instructions):continue
            match=[i for i in instructions if i.address==target and i.mnemonic=='call' and i.size==6]
            if not match:continue
            found.append({'start':hex(start),'first':instructions[0].mnemonic,
                          'before':[{'address':hex(i.address),'mnemonic':i.mnemonic,'operands':i.op_str}
                                    for i in instructions if target-32<=i.address<=target+16]})
        reports.append({'target':hex(target),'boundary_candidates':found})
    out=ROOT/'private/analysis/timegettime_static.json';out.write_text(json.dumps({'sha256':EXPECTED,'scope':'static byte-boundary candidates; no reachability proof','reports':reports},indent=2)+'\n',encoding='utf-8')
    for r in reports:print(r['target'],'aligned candidate starts:',len(r['boundary_candidates']),[v['start'] for v in r['boundary_candidates']])

if __name__=='__main__':main()
