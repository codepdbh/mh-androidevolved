"""Read-only, bounded disassembly of fixed timer dependency candidates."""
import hashlib,json
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,EXPECTED

def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    pe=pefile.PE(data=data);base=pe.OPTIONAL_HEADER.ImageBase;decoder=Cs(CS_ARCH_X86,CS_MODE_32)
    addresses=(0x401030,0x426ef0,0x481330,0x481340,0x493230,0x4932f0,0x5daa20,0x5daa50,0x604d20,0x604dc0,0x604f30,0x605750,0x608410,0x648540)
    entries=[]
    for address in addresses:
        section=pe.get_section_by_rva(address-base)
        if not section or section.Name.rstrip(b'\0')!=b'.text':raise SystemExit('dependency outside expected section')
        instructions=[]
        for i in decoder.disasm(pe.get_data(address-base,96),address):
            instructions.append({'address':hex(i.address),'mnemonic':i.mnemonic,'operands':i.op_str})
            if i.mnemonic.startswith('ret') or i.mnemonic=='jmp':break
        if not instructions or int(instructions[0]['address'],16)!=address:raise SystemExit('dependency decode failed')
        entries.append({'address':hex(address),'instructions':instructions})
    out=ROOT/'private/analysis/candidate_time/dependency_windows.json'
    out.write_text(json.dumps({'input_sha256':EXPECTED,'scope':'first 96 bytes or first return/jump; no reachability proof','entries':entries},indent=2)+'\n',encoding='utf-8')
    print('decoded',len(entries),'bounded dependency windows; full output remains private')

if __name__=='__main__':main()
