"""Lift the game's pool allocator (allocate 0x401350, free 0x401b00) to one private unit.

Eleven functions, 365 instructions, no Windows API calls. Every direct call is
checked with capstone and rewritten with its exact return address. The single
`rep stosb` (memset on a raw host pointer in PCRecomp's output) is replaced by
the bounds-checked mh_recomp_rep_stos from recomp/checked_memory_adapter.h.
"""
import hashlib,json,re,sys
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,PCRECOMP,EXPECTED,REVISION
FUNCTIONS={0x4010b0:(85,{0x610be0}),0x401350:(77,{0x401430,0x401520,0x401540,0x401580}),0x401430:(72,set()),0x401520:(10,set()),0x401540:(3,set()),
           0x401580:(11,set()),0x401b00:(33,{0x401540,0x401850,0x4018b0,0x401b80,0x401b90,0x401ba0}),0x401ba0:(116,set()),
           0x401b80:(2,set()),0x401b90:(2,set()),0x4018b0:(13,set()),0x401850:(26,set())}
ALLOWED={'MEM8','MEM16','MEM32','PUSH32','POP32_VAL','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT'}
PURE_HELPERS={'recomp_flags_pack'}
CALL=re.compile(r'RECOMP_CALL\(sub_([0-9A-F]{8})\); /\* 0x([0-9A-F]{8}): call 0x([0-9a-f]+) \*/')
STOS=('{ uint32_t _n = ecx, _b = _n * 1u; /* 0x0040159D: rep stosb byte ptr es:[edi], al */ if (_df > 0) { memset((void*)ADDR(edi), LO8(eax), _n); edi += _b; } '
      'else { memset((void*)ADDR(edi - _b + 1u), LO8(eax), _n); edi -= _b; } ecx = 0; }')
STOS_CHECKED=('{ uint32_t _n = ecx, _b = _n * 1u; /* 0x0040159D: rep stosb byte ptr es:[edi], al (checked) */ mh_recomp_rep_stos(edi, eax, _n, 1u, _df); '
              'if (_df > 0) edi += _b; else edi -= _b; ecx = 0; }')
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
    sources=[];items=[]
    for address,(count,callees) in FUNCTIONS.items():
        func=dis.disassemble_function(address,iat)
        if not func:raise SystemExit(f'no function at {address:#x}')
        instructions=[i for b in func.blocks.values() for i in b.instructions]
        if len(instructions)!=count or set(func.calls_to)!=callees:raise SystemExit(f'unexpected extent or calls at {address:#x}')
        start=min(i.address for i in instructions);end=max(i.address+i.size for i in instructions)
        if start!=address or end-start>0x400:raise SystemExit(f'unexpected range at {address:#x}')
        code=pe.get_data(start-base,end-start)
        source=Lifter(iat_map=iat).lift_function(func)
        if 'RECOMP_TODO' in source or 'ICALL' in source:raise SystemExit(f'unsupported construct at {address:#x}')
        lifted=hashlib.sha256(source.encode()).hexdigest();sites=[];rewrites=[]
        if address==0x401580:
            if source.count(STOS)!=1:raise SystemExit('unexpected rep stos form')
            source=source.replace(STOS,STOS_CHECKED);rewrites.append('rep stosb -> mh_recomp_rep_stos')
        if 'ADDR(' in source or 'memset(' in source or 'memcpy(' in source:raise SystemExit(f'raw guest pointer left at {address:#x}')
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
        if not helpers.issubset(PURE_HELPERS):raise SystemExit(f'unchecked runtime helpers at {address:#x}: '+','.join(sorted(helpers-PURE_HELPERS)))
        operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',source))
        if not operations.issubset(ALLOWED):raise SystemExit(f'unsupported operations at {address:#x}: '+','.join(sorted(operations-ALLOWED)))
        sources.append(source)
        items.append({'address':hex(address),'instructions':count,'range':[hex(start),hex(end)],'bytes_sha256':hashlib.sha256(code).hexdigest(),
                      'lifted_sha256':lifted,'sites':sites,'rewrites':rewrites,'operations':sorted(operations)})
    header=''.join(f'void sub_{a:08X}(void);\n' for a in sorted(set(FUNCTIONS)|{0x610be0}))  # 0x610be0: CRT malloc, unresolved
    unit=header+'\n'.join(sources)+'\n'
    out=ROOT/'private/analysis/allocator';out.mkdir(parents=True,exist_ok=True)
    (out/'allocator_unit.c').write_text(unit,encoding='utf-8',newline='\n')
    (out/'allocator_report.json').write_text(json.dumps({'input_sha256':EXPECTED,'pcrecomp_revision':REVISION,'items':items,
        'unit_sha256':hashlib.sha256(unit.encode()).hexdigest(),
        'unresolved':['0x610be0 CRT malloc (arena)'],'limitations':['pool layout inferred from code','not integrated into game']},indent=2)+'\n',encoding='utf-8')
    print('translated',len(items),'allocator functions,',sum(i['instructions'] for i in items),'instructions; unit remains private')
if __name__=='__main__':main()
