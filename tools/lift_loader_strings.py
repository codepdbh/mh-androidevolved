"""Lift the remaining direct callees of the loader 0x605750 to one private unit.

Functions: block reader 0x6059a0, string copy-constructor 0x4f2400, string
assign 0x4f2590, append-C-string 0x4f2a40, append core 0x4f28c0, string
release 0x4f2520 and the allocation wrapper 0x401020. Every direct call is
checked with capstone (5-byte E8) and rewritten with its exact return address.
The pool allocator 0x401350 and pool free 0x401b00 remain unresolved.
"""
import hashlib,json,re,sys
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,PCRECOMP,EXPECTED,REVISION
FUNCTIONS={0x6059a0:(25,{0x60ff60}),0x4f2400:(14,{0x4f2590}),0x4f2590:(74,{0x401020,0x401030,0x611640}),
           0x4f2a40:(18,{0x4f28c0}),0x4f28c0:(118,{0x401020,0x401030,0x4f2400,0x611640}),
           0x4f2520:(13,{0x401030}),0x401020:(4,{0x401350})}
ALLOWED={'MEM8','MEM16','MEM32','PUSH32','POP32_VAL','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT'}
CALL=re.compile(r'RECOMP_CALL\(sub_([0-9A-F]{8})\); /\* 0x([0-9A-F]{8}): call 0x([0-9a-f]+) \*/')
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    if (PCRECOMP/'REVISION.txt').read_text(encoding='ascii').strip()!=REVISION:raise SystemExit('unexpected tool revision')
    pe=pefile.PE(data=data,fast_load=True);base=pe.OPTIONAL_HEADER.ImageBase;decoder=Cs(CS_ARCH_X86,CS_MODE_32)
    for part in ('pe','disasm','lift'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from pe_analyze import analyze_pe,build_iat_map
    from disasm32 import Disassembler
    from lift32 import Lifter
    info=analyze_pe(str(GAME));iat=build_iat_map(info);dis=Disassembler(data,info.image_base,info.sections)
    sources=[];items=[];declared=set()
    for address,(count,callees) in FUNCTIONS.items():
        func=dis.disassemble_function(address,iat)
        if not func:raise SystemExit(f'no function at {address:#x}')
        instructions=[i for b in func.blocks.values() for i in b.instructions]
        if len(instructions)!=count or set(func.calls_to)!=callees:raise SystemExit(f'unexpected extent or calls at {address:#x}')
        start=min(i.address for i in instructions);end=max(i.address+i.size for i in instructions)
        if start!=address or end-start>0x400:raise SystemExit(f'unexpected range at {address:#x}')
        code=pe.get_data(start-base,end-start)
        source=Lifter(iat_map=iat).lift_function(func)
        if 'RECOMP_TODO' in source or 'ADDR(' in source:raise SystemExit(f'unsupported construct at {address:#x}')
        lifted=hashlib.sha256(source.encode()).hexdigest();sites=[]
        def rewrite(m):
            target=int(m.group(1),16);site=int(m.group(2),16)
            if target!=int(m.group(3),16) or target not in callees:raise SystemExit(f'call target mismatch at {site:#x}')
            ins=list(decoder.disasm(pe.get_data(site-base,5),site,count=1))
            if len(ins)!=1 or ins[0].mnemonic!='call' or ins[0].size!=5 or int(ins[0].op_str,16)!=target:raise SystemExit(f'call decoding mismatch at {site:#x}')
            sites.append({'call':hex(site),'target':hex(target),'return':hex(site+5)})
            return f'MH_RECOMP_CALL_AT(sub_{target:08X}, 0x{site+5:08X}u);'
        source=CALL.sub(rewrite,source)
        if 'RECOMP_CALL(' in source:raise SystemExit(f'unadapted call at {address:#x}')
        helpers=set(re.findall(r'\b(recomp_\w+)\s*\(',source))
        if helpers:raise SystemExit(f'unchecked runtime helpers at {address:#x}: '+','.join(sorted(helpers)))
        operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',source))
        if not operations.issubset(ALLOWED):raise SystemExit(f'unsupported operations at {address:#x}: '+','.join(sorted(operations-ALLOWED)))
        declared|=callees;sources.append(source)
        items.append({'address':hex(address),'instructions':count,'range':[hex(start),hex(end)],'bytes_sha256':hashlib.sha256(code).hexdigest(),
                      'lifted_sha256':lifted,'sites':sites,'operations':sorted(operations)})
    header=''.join(f'void sub_{a:08X}(void);\n' for a in sorted(declared|set(FUNCTIONS)))
    unit=header+'\n'.join(sources)+'\n'
    out=ROOT/'private/analysis/candidate_time/dependencies';out.mkdir(parents=True,exist_ok=True)
    (out/'loader_strings_unit.c').write_text(unit,encoding='utf-8',newline='\n')
    (out/'loader_strings_report.json').write_text(json.dumps({'input_sha256':EXPECTED,'pcrecomp_revision':REVISION,'items':items,
        'unit_sha256':hashlib.sha256(unit.encode()).hexdigest(),
        'unresolved':['0x401350 pool allocate','0x401b00 pool free'],
        'limitations':['string layout inferred from code, not documentation','reachability unproved','not integrated into game']},indent=2)+'\n',encoding='utf-8')
    print('translated',len(items),'loader functions; unit remains private')
if __name__=='__main__':main()
