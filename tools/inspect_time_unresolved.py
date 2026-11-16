"""Low-memory read-only windows of unresolved timer dependencies, never execution."""
import hashlib,json,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_X86,CS_MODE_32

ROOT=Path(__file__).resolve().parents[1]
GAME=ROOT/'Manhunt Collection/Manhunt/manhunt.exe'
EXPECTED='5001b64f77690316330575fcfe6acd5c5115c5476c183ffec0d86779b0686b52'
TARGETS=(0x401030,0x401b00,0x493230,0x4932f0,0x4f2400,0x4f2520,0x4f2a40,0x605750,0x6059a0,0x605e40,0x60fea0,0x60feb0,0x60fec0,0x60ff60)

def main():
    with GAME.open('rb') as f:
        digest=hashlib.sha256()
        while block:=f.read(65536):digest.update(block)
        if digest.hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
        f.seek(0);dos=f.read(64)
        if dos[:2]!=b'MZ':raise SystemExit('invalid DOS header')
        offset=struct.unpack_from('<I',dos,0x3c)[0]
        if offset>1024*1024:raise SystemExit('PE header out of budget')
        f.seek(offset);header=f.read(24)
        if len(header)!=24 or header[:4]!=b'PE\0\0':raise SystemExit('invalid PE header')
        machine,count=struct.unpack_from('<HH',header,4);optional_size=struct.unpack_from('<H',header,20)[0]
        if machine!=0x14c or not 1<=count<=96 or not 32<=optional_size<=4096:raise SystemExit('unexpected PE layout')
        optional=f.read(optional_size)
        if len(optional)!=optional_size or struct.unpack_from('<H',optional)[0]!=0x10b:raise SystemExit('expected PE32')
        imagebase=struct.unpack_from('<I',optional,28)[0];sections=[]
        for _ in range(count):
            entry=f.read(40)
            if len(entry)!=40:raise SystemExit('truncated section table')
            size,rva,raw_size,raw=struct.unpack_from('<IIII',entry,8)
            sections.append((entry[:8].rstrip(b'\0'),rva,raw_size,raw))
        reports=[];decoder=Cs(CS_ARCH_X86,CS_MODE_32)
        for address in TARGETS:
            relative=address-imagebase
            section=next((s for s in sections if s[0]==b'.text' and s[1]<=relative<s[1]+s[2]),None)
            if section is None:raise SystemExit('target outside raw .text')
            _,rva,raw_size,raw=section;delta=relative-rva;length=min(2048,raw_size-delta)
            f.seek(raw+delta);code=f.read(length)
            if len(code)!=length:raise SystemExit('truncated code window')
            ins=list(decoder.disasm(code,address,count=256 if address==0x605750 else 192))
            if not ins or ins[0].address!=address:raise SystemExit('target did not decode')
            reports.append({'address':hex(address),'scope':'linear window only, not recovered function',
                'instructions':[{'address':hex(i.address),'size':i.size,'mnemonic':i.mnemonic,'operands':i.op_str} for i in ins]})
    output=ROOT/'private/analysis/candidate_time/unresolved_windows.json';output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({'input_sha256':EXPECTED,'reports':reports},indent=2)+'\n',encoding='utf-8')
    for item in reports:
        first_return=next((i['address'] for i in item['instructions'] if i['mnemonic'].startswith('ret')),None)
        print(item['address'],'decoded:',len(item['instructions']),'first linear return:',first_return)

if __name__=='__main__':main()
