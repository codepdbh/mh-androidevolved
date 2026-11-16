"""Lift a bounded recorded loader candidate, not the whole image or callees."""
import hashlib,json,re,sys
from pathlib import Path
from types import SimpleNamespace
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
ROOT=Path(__file__).resolve().parents[1];GAME=ROOT/'Manhunt Collection/Manhunt/manhunt.exe';PCRECOMP=ROOT/'private/pcrecomp'
EXPECTED='5001b64f77690316330575fcfe6acd5c5115c5476c183ffec0d86779b0686b52'
REVISION='93a74327f33d399d2bf4ee606c7a72388c193617';ADDRESS=0x605750;END=0x605998
CALLEES={0x4f2400,0x4f2520,0x4f2a40,0x6059a0,0x605e40,0x60fea0,0x60feb0,0x60fec0,0x60ff60}
def main():
    with GAME.open('rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    if (PCRECOMP/'REVISION.txt').read_text().strip()!=REVISION:raise SystemExit('unexpected tool revision')
    pe=pefile.PE(str(GAME),fast_load=True);imagebase=pe.OPTIONAL_HEADER.ImageBase
    code=pe.get_data(ADDRESS-imagebase,END-ADDRESS);pe.close()
    if len(code)!=END-ADDRESS:raise SystemExit('incomplete bounded window')
    for part in ('disasm','lift'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from disasm32 import Disassembler
    from lift32 import Lifter
    section=SimpleNamespace(name='.text',virtual_address=ADDRESS-imagebase,virtual_size=len(code),raw_offset=0,raw_size=len(code),is_code=True)
    function=Disassembler(code,imagebase,[section]).disassemble_function(ADDRESS,{})
    if not function:raise SystemExit('bounded candidate not recovered')
    instructions=[i for block in function.blocks.values() for i in block.instructions]
    direct_calls={i.get_branch_target() for i in instructions if i.is_call}
    if len(instructions)!=180 or direct_calls!=CALLEES:raise SystemExit(f'candidate extent or callees mismatch: {len(instructions)} instructions, {sorted(direct_calls)}')
    # The sparse section deliberately excludes callees, so PCRecomp cannot
    # classify them via is_code_address; the exact decoded targets were checked.
    function.calls_to=direct_calls
    if any(i.address<ADDRESS or i.end_address>END for i in instructions):raise SystemExit('candidate left bounded window')
    source=Lifter(iat_map={}).lift_function(function);original=hashlib.sha256(source.encode()).hexdigest()
    decoder=Cs(CS_ARCH_X86,CS_MODE_32);sites=[]
    for ins in instructions:
        if not ins.is_call:continue
        target=ins.get_branch_target();site=ins.address
        if target not in CALLEES or ins.size!=5:raise SystemExit('unexpected call kind')
        decoded=list(decoder.disasm(code[site-ADDRESS:site-ADDRESS+5],site,count=1))
        if len(decoded)!=1 or decoded[0].mnemonic!='call' or decoded[0].size!=5 or int(decoded[0].op_str,16)!=target:raise SystemExit('call revalidation failed')
        pattern=rf'RECOMP_CALL\(sub_{target:08X}\); /\* 0x{site:08X}: call 0x{target:x} \*/'
        source,n=re.subn(pattern,f'MH_RECOMP_CALL_AT(sub_{target:08X}, 0x{site+5:08X}u);',source)
        if n!=1:raise SystemExit('call replacement mismatch')
        sites.append({'call':hex(site),'target':hex(target),'return':hex(site+5)})
    if 'RECOMP_TODO' in source or 'ADDR(' in source:raise SystemExit('unsupported translation operation')
    operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',source))
    if not operations.issubset({'MEM8','MEM16','MEM32','PUSH32','POP32_VAL','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT'}):raise SystemExit('unchecked helper operations: '+str(sorted(operations)))
    header=''.join(f'void sub_{target:08X}(void);\n' for target in sorted(CALLEES));text=header+source
    folder=ROOT/'private/analysis/candidate_time/dependencies';folder.mkdir(parents=True,exist_ok=True)
    (folder/'dep_00605750_precise.c').write_text(text+'\n',encoding='utf-8')
    (folder/'loader_report.json').write_text(json.dumps({'address':hex(ADDRESS),'end':hex(END),'input_sha256':EXPECTED,'pcrecomp_revision':REVISION,
        'instructions':len(instructions),'blocks':len(function.blocks),'bytes_sha256':hashlib.sha256(code).hexdigest(),
        'lifted_sha256':original,'adapted_sha256':hashlib.sha256(text.encode()).hexdigest(),'sites':sites,
        'limitations':['bounded candidate; game reachability not proved','nine direct callees unresolved','not executed or integrated']},indent=2)+'\n',encoding='utf-8')
    print('bounded candidate: 180 instructions;',len(sites),'verified direct call sites; nine callees unresolved')
if __name__=='__main__':main()
