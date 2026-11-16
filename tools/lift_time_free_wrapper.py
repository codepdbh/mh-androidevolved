"""Lift exactly four verified instructions without a whole-image analysis."""
import hashlib,json,re,sys
from pathlib import Path
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32

ROOT=Path(__file__).resolve().parents[1];GAME=ROOT/'Manhunt Collection/Manhunt/manhunt.exe'
PCRECOMP=ROOT/'private/pcrecomp';ADDRESS=0x401030
EXPECTED='5001b64f77690316330575fcfe6acd5c5115c5476c183ffec0d86779b0686b52'
REVISION='93a74327f33d399d2bf4ee606c7a72388c193617'

def main():
    with GAME.open('rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    if (PCRECOMP/'REVISION.txt').read_text().strip()!=REVISION:raise SystemExit('unexpected tool revision')
    pe=pefile.PE(str(GAME),fast_load=True);code=pe.get_data(ADDRESS-pe.OPTIONAL_HEADER.ImageBase,15);pe.close()
    decoder=Cs(CS_ARCH_X86,CS_MODE_32);decoder.detail=True;ins=list(decoder.disasm(code,ADDRESS))
    expected=[('push','dword ptr [esp + 4]'),('mov','ecx, 0x67d000'),('call','0x401b00'),('ret','')]
    if [(i.mnemonic,i.op_str) for i in ins]!=expected or sum(i.size for i in ins)!=15:raise SystemExit('wrapper instruction mismatch')
    for part in ('disasm','lift'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from disasm32 import Instruction,BasicBlock,Function
    from lift32 import Lifter
    instructions=[Instruction(i.address,i.size,i.mnemonic,i.op_str,bytes(i.bytes),list(i.operands)) for i in ins]
    block=BasicBlock(ADDRESS,ADDRESS+15,instructions,[],True)
    function=Function(address=ADDRESS,end=ADDRESS+15,name='sub_00401030',blocks={ADDRESS:block},calls_to={0x401b00},size=15)
    source=Lifter(iat_map={}).lift_function(function);original=hashlib.sha256(source.encode()).hexdigest()
    source,n=re.subn(r'RECOMP_CALL\(sub_00401B00\); /\* 0x00401039: call 0x401b00 \*/','MH_RECOMP_CALL_AT(sub_00401B00, 0x0040103Eu);',source)
    if n!=1 or 'RECOMP_TODO' in source:raise SystemExit('unexpected wrapper translation')
    operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',source))
    if not operations.issubset({'MEM32','PUSH32','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT'}):raise SystemExit('unsupported wrapper operations')
    text='void sub_00401B00(void);\n'+source;folder=ROOT/'private/analysis/candidate_time/dependencies';folder.mkdir(parents=True,exist_ok=True)
    (folder/'dep_00401030_precise.c').write_text(text+'\n',encoding='utf-8')
    (folder/'free_wrapper_report.json').write_text(json.dumps({'address':hex(ADDRESS),'input_sha256':EXPECTED,'pcrecomp_revision':REVISION,
        'instructions':4,'bytes_sha256':hashlib.sha256(code).hexdigest(),'lifted_sha256':original,'adapted_sha256':hashlib.sha256(text.encode()).hexdigest(),
        'call':'0x401039','return':'0x40103e','dependency':'0x401b00',
        'limitations':['callee unresolved','no reachability proof','not tested or integrated']},indent=2)+'\n',encoding='utf-8')
    print('verified and lifted four instructions; callee 0x401b00 unresolved')

if __name__=='__main__':main()
