"""Static, bounded inspection of two GetTickCount references; no execution."""
import hashlib,json
from pathlib import Path
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,EXPECTED

def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    pe=pefile.PE(data=data);base=pe.OPTIONAL_HEADER.ImageBase
    targets={0x4fb920,0x4fb934};starts=[]
    section=next((s for s in pe.sections if s.Name.rstrip(b'\0')==b'.text'),None)
    if section is None:raise SystemExit('missing .text')
    code=section.get_data();section_base=base+section.VirtualAddress
    for va in range(min(targets)-512,min(targets)+1):
        offset=va-section_base
        if offset>0 and (code[offset:offset+3]==b'\x55\x8b\xec' or code[offset-1] in (0xc3,0xcc)):
            starts.append(va)
    decoder=Cs(CS_ARCH_X86,CS_MODE_32);candidates=[]
    for start in starts:
        offset=start-section_base;instructions=list(decoder.disasm(code[offset:offset+768],start))
        found=[i for i in instructions if i.address in targets and i.mnemonic=='call' and i.size==6]
        premature_return=any(i.mnemonic.startswith('ret') and i.address<max(targets) for i in instructions)
        if len(found)==len(targets) and not premature_return:
            candidates.append({'start':hex(start),'last':hex(instructions[-1].address) if instructions else None,
                               'instructions':[{'address':hex(i.address),'mnemonic':i.mnemonic,'operands':i.op_str}
                                               for i in instructions if i.address<=max(targets)+32]})
    out=ROOT/'private/analysis/tick_candidate_static.json';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({'sha256':EXPECTED,'scope':'static prologue candidates; reachability and actual function boundaries unproven',
                               'call_sites':[hex(x) for x in sorted(targets)],'candidates':candidates},indent=2)+'\n',encoding='utf-8')
    print('boundary-pattern candidates:',len(starts),'aligned candidates:',len(candidates))
    for item in candidates:print('candidate start:',item['start'])

if __name__=='__main__':main()
