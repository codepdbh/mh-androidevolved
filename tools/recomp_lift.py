"""Audited translation of a closed set of game functions into one private C unit.

lift_closure(roots, stop, imports, name) walks the direct-call graph from
`roots` (not descending into `stop`), lifts every function with the pinned
PCRecomp revision and applies only these verified rewrites:
- direct calls (5-byte E8, checked with capstone) -> MH_RECOMP_CALL_AT(fn, exact return);
- calls through allowed import slots (6-byte FF 15) -> MH_RECOMP_ICALL_AT(slot, exact return);
- `rep stos{b,w,d}` (memset on a raw host pointer) -> bounds-checked mh_recomp_rep_stos;
- `recomp_rep_movs` -> bounds-checked mh_recomp_rep_movs.
Anything else that is unsafe or unsupported (raw ADDR, x87, unknown runtime
helpers, other indirect calls, RECOMP_TODO) aborts the translation.
The executable hash and the PCRecomp revision are verified first; output and
report go to private/analysis/<name>/ and are never published.
"""
import hashlib,json,re,sys
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,PCRECOMP,EXPECTED,REVISION
ALLOWED={'MEM8','MEM16','MEM32','PUSH32','POP32_VAL','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT'}
PURE_HELPERS={'recomp_flags_pack'}
CALL=re.compile(r'RECOMP_CALL\(sub_([0-9A-F]{8})\); /\* 0x([0-9A-F]{8}): call 0x([0-9a-f]+) \*/')
ICALL=re.compile(r'RECOMP_ICALL\(MEM32\(0x([0-9A-F]+)\)\); /\* 0x([0-9A-F]{8}): call dword ptr \[0x([0-9a-f]+)\] \*/')
STOS=re.compile(r'\{ uint32_t _n = ecx, _b = _n \* ([124])u; /\* (0x[0-9A-F]{8}: rep stos[bwd] [^*]*?) \*/ '
                r'if \(_df > 0\) \{ (?:memset|MEMSET16|MEMSET32)\(\(void\*\)ADDR\(edi\), (?:LO8\(eax\)|LO16\(eax\)|eax), _n\); edi \+= _b; \} '
                r'else \{ (?:memset|MEMSET16|MEMSET32)\(\(void\*\)ADDR\(edi - _b \+ \1u\), (?:LO8\(eax\)|LO16\(eax\)|eax), _n\); edi -= _b; \} ecx = 0; \}')

def _tools():
    for part in ('pe','disasm','lift'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from pe_analyze import analyze_pe,build_iat_map
    from disasm32 import Disassembler
    from lift32 import Lifter
    return analyze_pe,build_iat_map,Disassembler,Lifter

def lift_closure(roots,stop,imports,name,max_functions=64):
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    if (PCRECOMP/'REVISION.txt').read_text(encoding='ascii').strip()!=REVISION:raise SystemExit('unexpected tool revision')
    if not re.fullmatch(r'[a-z0-9_]{1,40}',name):raise SystemExit('invalid unit name')
    pe=pefile.PE(data=data);base=pe.OPTIONAL_HEADER.ImageBase;decoder=Cs(CS_ARCH_X86,CS_MODE_32)
    names={}
    for entry in pe.DIRECTORY_ENTRY_IMPORT:
        for imp in entry.imports:names[imp.address]=imp.name.decode() if imp.name else f'ordinal_{imp.ordinal}'
    for slot in imports:
        if slot not in names:raise SystemExit(f'{slot:#x} is not an import slot')
    analyze_pe,build_iat_map,Disassembler,Lifter=_tools()
    info=analyze_pe(str(GAME));iat=build_iat_map(info);dis=Disassembler(data,info.image_base,info.sections)
    order=[];pending=list(roots);graph={}
    while pending:
        address=pending.pop(0)
        if address in graph or address in stop:continue
        func=dis.disassemble_function(address,iat)
        if not func:raise SystemExit(f'no function at {address:#x}')
        graph[address]=func;order.append(address)
        if len(order)>max_functions:raise SystemExit('closure larger than allowed; add stop points')
        pending.extend(sorted(func.calls_to))
    sources=[];items=[];used_imports=set()
    for address in order:
        func=graph[address];instructions=[i for b in func.blocks.values() for i in b.instructions]
        start=min(i.address for i in instructions);end=max(i.address+i.size for i in instructions)
        if start!=address or end-start>0x2000:raise SystemExit(f'unexpected range at {address:#x}')
        source=Lifter(iat_map=iat).lift_function(func)
        if 'RECOMP_TODO' in source:raise SystemExit(f'unsupported instruction at {address:#x}')
        lifted=hashlib.sha256(source.encode()).hexdigest();sites=[];rewrites=[]
        def direct(m):
            target=int(m.group(1),16);site=int(m.group(2),16)
            if target!=int(m.group(3),16) or target not in func.calls_to:raise SystemExit(f'call target mismatch at {site:#x}')
            ins=list(decoder.disasm(pe.get_data(site-base,5),site,count=1))
            if len(ins)!=1 or ins[0].mnemonic!='call' or ins[0].size!=5 or int(ins[0].op_str,16)!=target:raise SystemExit(f'call decoding mismatch at {site:#x}')
            sites.append({'call':hex(site),'target':hex(target),'return':hex(site+5)})
            return f'MH_RECOMP_CALL_AT(sub_{target:08X}, 0x{site+5:08X}u);'
        def indirect(m):
            slot=int(m.group(1),16);site=int(m.group(2),16)
            if slot!=int(m.group(3),16) or slot not in imports:raise SystemExit(f'indirect call through {slot:#x} at {site:#x} is not an allowed import')
            ins=list(decoder.disasm(pe.get_data(site-base,6),site,count=1))
            if len(ins)!=1 or ins[0].mnemonic!='call' or ins[0].size!=6 or ins[0].bytes[:2]!=b'\xff\x15':raise SystemExit(f'import call decoding mismatch at {site:#x}')
            used_imports.add(slot);sites.append({'call':hex(site),'import':names[slot],'slot':hex(slot),'return':hex(site+6)})
            return f'MH_RECOMP_ICALL_AT(MEM32(0x{slot:X}), 0x{site+6:08X}u);'
        def stos(m):
            rewrites.append('rep stos '+m.group(2).split(':')[0])
            return (f'{{ uint32_t _n = ecx, _b = _n * {m.group(1)}u; /* {m.group(2)} (checked) */ mh_recomp_rep_stos(edi, eax, _n, {m.group(1)}u, _df); '
                    'if (_df > 0) edi += _b; else edi -= _b; ecx = 0; }')
        source=CALL.sub(direct,source);source=ICALL.sub(indirect,source);source=STOS.sub(stos,source)
        source,n=re.subn(r'\brecomp_rep_movs\(','mh_recomp_rep_movs(',source)
        if n:rewrites.append(f'{n} rep movs')
        code_only=re.sub(r'/\*.*?\*/','',source,flags=re.DOTALL)  # validate code, not PCRecomp's comments
        left=re.findall(r'\bADDR\(|\bmemset\(|\bmemcpy\(|MEMSET\d*\(|RECOMP_CALL\(|RECOMP_ICALL\(|RECOMP_JMP\w*|\bfp_\w+\(|\b_st\[|\bg_st\b',code_only)
        if left:raise SystemExit(f'unsupported or unchecked construct left at {address:#x}: '+', '.join(sorted(set(left))))
        helpers=set(re.findall(r'\b(recomp_\w+)\s*\(',code_only))
        if not helpers.issubset(PURE_HELPERS):raise SystemExit(f'unchecked runtime helpers at {address:#x}: '+','.join(sorted(helpers-PURE_HELPERS)))
        operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',code_only))
        if not operations.issubset(ALLOWED):raise SystemExit(f'unsupported operations at {address:#x}: '+','.join(sorted(operations-ALLOWED)))
        sources.append(source)
        items.append({'address':hex(address),'instructions':len(instructions),'range':[hex(start),hex(end)],
                      'bytes_sha256':hashlib.sha256(pe.get_data(start-base,end-start)).hexdigest(),'lifted_sha256':lifted,
                      'sites':sites,'rewrites':rewrites,'operations':sorted(operations)})
    declared=set(order)|{int(s['target'],16) for i in items for s in i['sites'] if 'target' in s}
    header=''.join(f'void sub_{a:08X}(void);\n' for a in sorted(declared))
    unit=header+'\n'.join(sources)+'\n'
    out=ROOT/'private/analysis'/name;out.mkdir(parents=True,exist_ok=True)
    (out/f'{name}_unit.c').write_text(unit,encoding='utf-8',newline='\n')
    report={'input_sha256':EXPECTED,'pcrecomp_revision':REVISION,'roots':[hex(r) for r in roots],'stop':[hex(s) for s in sorted(stop)],
            'imports':{hex(s):names[s] for s in sorted(used_imports)},'items':items,'unit_sha256':hashlib.sha256(unit.encode()).hexdigest()}
    (out/f'{name}_report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report
