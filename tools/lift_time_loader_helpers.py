"""Lift exactly verified helper instruction windows; no game or file API execution."""
import hashlib,json,re,sys
from pathlib import Path
from types import SimpleNamespace
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
ROOT=Path(__file__).resolve().parents[1];GAME=ROOT/'Manhunt Collection/Manhunt/manhunt.exe';PCRECOMP=ROOT/'private/pcrecomp'
EXPECTED='5001b64f77690316330575fcfe6acd5c5115c5476c183ffec0d86779b0686b52'
REVISION='93a74327f33d399d2bf4ee606c7a72388c193617'
SPECS={0x605e40:(7,[('lea','eax, [ecx + 0x2ac]'),('ret','')]),
       0x60fea0:(9,[('mov','eax, ecx'),('mov','dword ptr [eax], 0xffffffff'),('ret','')]),
       0x60ff60:(25,[('push','0'),('push','dword ptr [esp + 0x10]'),('push','dword ptr [esp + 0x10]'),('push','dword ptr [esp + 0x10]'),('push','dword ptr [ecx]'),('call','dword ptr [0x81b374]'),('ret','0xc')])}
def main():
    with GAME.open('rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    if (PCRECOMP/'REVISION.txt').read_text().strip()!=REVISION:raise SystemExit('unexpected tool revision')
    for part in ('disasm','lift'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from disasm32 import Disassembler
    from lift32 import Lifter
    pe=pefile.PE(str(GAME),fast_load=True);imagebase=pe.OPTIONAL_HEADER.ImageBase;decoder=Cs(CS_ARCH_X86,CS_MODE_32)
    folder=ROOT/'private/analysis/candidate_time/dependencies';items=[]
    for address,(length,expected_ins) in SPECS.items():
        code=pe.get_data(address-imagebase,length);ins=list(decoder.disasm(code,address))
        if len(code)!=length or [(i.mnemonic,i.op_str) for i in ins]!=expected_ins or sum(i.size for i in ins)!=length:raise SystemExit('helper instruction mismatch')
        section=SimpleNamespace(name='.text',virtual_address=address-imagebase,virtual_size=length,raw_size=length,raw_offset=0,is_code=True)
        function=Disassembler(code,imagebase,[section]).disassemble_function(address,{})
        if not function or sum(len(b.instructions) for b in function.blocks.values())!=len(expected_ins) or function.calls_to:raise SystemExit('unexpected helper extent')
        source=Lifter(iat_map={}).lift_function(function);original=hashlib.sha256(source.encode()).hexdigest()
        if address==0x60ff60:
            source,n=re.subn(r'RECOMP_ICALL\(MEM32\(0x81B374\)\); /\* 0x0060FF70: call dword ptr \[0x81b374\] \*/','MH_RECOMP_ICALL_AT(MEM32(0x81B374), 0x0060FF76u);',source)
            if n!=1:raise SystemExit('ReadFile wrapper call replacement mismatch')
        operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',source))
        if 'RECOMP_TODO' in source or not operations.issubset({'MEM32','PUSH32','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT'}):raise SystemExit('unsupported helper operations')
        name=f'dep_{address:08x}_precise.c';(folder/name).write_text(source+'\n',encoding='utf-8')
        items.append({'address':hex(address),'source':name,'bytes_length':length,'bytes_sha256':hashlib.sha256(code).hexdigest(),
                      'instructions':len(ins),'lifted_sha256':original,'adapted_sha256':hashlib.sha256(source.encode()).hexdigest()})
    pe.close()
    (folder/'loader_helpers_report.json').write_text(json.dumps({'input_sha256':EXPECTED,'pcrecomp_revision':REVISION,'items':items,
        'limitations':['ReadFile not implemented','not integrated into main harness','game reachability not proved']},indent=2)+'\n',encoding='utf-8')
    print('three verified helpers translated; ReadFile implementation unresolved')
if __name__=='__main__':main()
