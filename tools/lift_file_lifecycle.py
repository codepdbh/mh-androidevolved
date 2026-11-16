"""Lift exact open/close wrapper windows; system APIs stay outside this code."""
import hashlib,json,re,sys
from pathlib import Path
from types import SimpleNamespace
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
ROOT=Path(__file__).resolve().parents[1];GAME=ROOT/'Manhunt Collection/Manhunt/manhunt.exe';PCRECOMP=ROOT/'private/pcrecomp'
EXPECTED='5001b64f77690316330575fcfe6acd5c5115c5476c183ffec0d86779b0686b52'
REVISION='93a74327f33d399d2bf4ee606c7a72388c193617'
SPECS={
0x60feb0:(12,[('push','ebx'),('mov','ebx, ecx'),('call','0x60ff40'),('mov','eax, ebx'),('pop','ebx'),('ret','')]),
0x60fec0:(49,[('push','ebx'),('mov','ebx, ecx'),('call','0x60ff40'),('push','0'),('push','dword ptr [esp + 0x14]'),('push','3'),('push','0'),('push','0'),('push','dword ptr [esp + 0x20]'),('push','dword ptr [esp + 0x20]'),('call','dword ptr [0x81b37c]'),('mov','dword ptr [ebx], eax'),('cmp','dword ptr [ebx], -1'),('setne','al'),('movzx','eax, al'),('pop','ebx'),('ret','0xc')]),
0x60ff40:(25,[('push','ebx'),('mov','ebx, ecx'),('mov','eax, dword ptr [ebx]'),('cmp','eax, -1'),('je','0x60ff57'),('push','eax'),('call','dword ptr [0x81b370]'),('mov','dword ptr [ebx], 0xffffffff'),('pop','ebx'),('ret','')])}
SITES={0x60feb3:(5,'0x60ff40'),0x60fec3:(5,'0x60ff40'),0x60fedc:(6,'dword ptr [0x81b37c]'),0x60ff4b:(6,'dword ptr [0x81b370]')}
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
        code=pe.get_data(address-imagebase,length);decoded=list(decoder.disasm(code,address))
        if [(i.mnemonic,i.op_str) for i in decoded]!=expected_ins or sum(i.size for i in decoded)!=length:raise SystemExit('lifecycle instruction mismatch')
        section=SimpleNamespace(name='.text',virtual_address=address-imagebase,virtual_size=length,raw_size=length,raw_offset=0,is_code=True)
        function=Disassembler(code,imagebase,[section]).disassemble_function(address,{})
        if not function:raise SystemExit('wrapper not recovered')
        instructions=[i for b in function.blocks.values() for i in b.instructions]
        if len(instructions)!=len(expected_ins):raise SystemExit('wrapper extent mismatch')
        function.calls_to={i.get_branch_target() for i in instructions if i.is_call and i.get_branch_target() is not None}
        source=Lifter(iat_map={}).lift_function(function);original=hashlib.sha256(source.encode()).hexdigest()
        for ins in instructions:
            if not ins.is_call:continue
            if ins.address not in SITES:raise SystemExit('unexpected call')
            size,target=SITES[ins.address]
            if ins.size!=size or ins.op_str!=target:raise SystemExit('call decoding mismatch')
            if size==5:
                old=f'RECOMP_CALL(sub_{int(target,16):08X});';new=f'MH_RECOMP_CALL_AT(sub_{int(target,16):08X}, 0x{ins.address+size:08X}u);'
            else:
                slot=0x81b37c if ins.address==0x60fedc else 0x81b370
                old=f'RECOMP_ICALL(MEM32(0x{slot:X}));';new=f'MH_RECOMP_ICALL_AT(MEM32(0x{slot:X}), 0x{ins.address+size:08X}u);'
            if source.count(old)!=1:raise SystemExit('unexpected call form')
            source=source.replace(old,new)
        operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',source))
        if 'RECOMP_TODO' in source or not operations.issubset({'MEM32','PUSH32','POP32_VAL','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT'}):raise SystemExit('unsupported lifecycle operations')
        header='void sub_0060FF40(void);\n' if address!=0x60ff40 else ''
        text=header+source;name=f'dep_{address:08x}_precise.c';(folder/name).write_text(text+'\n',encoding='utf-8')
        items.append({'address':hex(address),'source':name,'instructions':len(instructions),'bytes_sha256':hashlib.sha256(code).hexdigest(),'lifted_sha256':original,'adapted_sha256':hashlib.sha256(text.encode()).hexdigest()})
    pe.close();(folder/'file_lifecycle_report.json').write_text(json.dumps({'input_sha256':EXPECTED,'items':items,'limitations':['CreateFileA/CloseHandle not supplied by translation','no game reachability proof','not whole-game tested']},indent=2)+'\n',encoding='utf-8')
    print('three file lifecycle wrappers translated with four validated call returns')
if __name__=='__main__':main()
