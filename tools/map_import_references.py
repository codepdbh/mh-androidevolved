"""Bounded PE import-reference candidates; decoded bytes are not proof of reachability."""
import hashlib,json,struct
from pathlib import Path
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from inspect_entrypoint import ROOT,GAME,EXPECTED

def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED: raise SystemExit('unexpected game hash')
    pe=pefile.PE(data=data)
    if pe.FILE_HEADER.Machine!=0x14c: raise SystemExit('expected x86 PE')
    imports={i.address:(e.dll.decode('ascii','replace'),i.name.decode('ascii','replace') if i.name else '#'+str(i.ordinal))
             for e in pe.DIRECTORY_ENTRY_IMPORT for i in e.imports}
    decoder=Cs(CS_ARCH_X86,CS_MODE_32)
    results=[]; code_sections=[]
    for section in pe.sections:
        name=section.Name.rstrip(b'\0').decode('ascii','replace')
        if name!='.text': continue
        code=section.get_data(); base=pe.OPTIONAL_HEADER.ImageBase+section.VirtualAddress
        code_sections.append((name,base,code))
        for pattern in (b'\xff\x15',b'\xff\x25'):
            pos=0
            while True:
                pos=code.find(pattern,pos)
                if pos<0 or pos+6>len(code): break
                slot=struct.unpack_from('<I',code,pos+2)[0]
                if slot in imports:
                    decoded=list(decoder.disasm(code[pos:pos+6],base+pos,count=1))
                    if decoded and decoded[0].size==6 and decoded[0].mnemonic in ('call','jmp'):
                        dll,symbol=imports[slot]
                        results.append({'address':hex(base+pos),'section':name,'kind':decoded[0].mnemonic,
                                        'iat_slot':hex(slot),'dll':dll,'symbol':symbol})
                pos+=1
    results.sort(key=lambda x:int(x['address'],16))
    thunks={int(item['address'],16):item for item in results if item['kind']=='jmp'}
    callers=[]
    for name,base,code in code_sections:
        pos=0
        while True:
            pos=code.find(b'\xe8',pos)
            if pos<0 or pos+5>len(code): break
            target=(base+pos+5+struct.unpack_from('<i',code,pos+1)[0]) & 0xffffffff
            if target in thunks:
                decoded=list(decoder.disasm(code[pos:pos+5],base+pos,count=1))
                if decoded and decoded[0].size==5 and decoded[0].mnemonic=='call':
                    thunk=thunks[target]
                    callers.append({'address':hex(base+pos),'section':name,'thunk':hex(target),
                                    'dll':thunk['dll'],'symbol':thunk['symbol']})
            pos+=1
    out=ROOT/'private/analysis/import_reference_candidates.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({'input_sha256':EXPECTED,'scope':'raw byte-pattern candidates; instruction boundaries and reachability unproven','references':results,'thunk_call_candidates':callers},indent=2)+'\n',encoding='utf-8')
    print(f'{len(results)} candidate import references, {len(callers)} potential thunk calls; private output={out}')

if __name__=='__main__':main()
