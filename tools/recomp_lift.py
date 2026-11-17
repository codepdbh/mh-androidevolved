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
PURE_HELPERS={'recomp_flags_pack','recomp_eflags'}  # pure functions of their arguments
# Closed list of macros allowed in translated code; any other uppercase macro call aborts.
MACROS={'MEM8','MEM16','MEM32','PUSH32','POP32_VAL','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT',
        'MH_RECOMP_CALL_AT','MH_RECOMP_ICALL_AT','MH_VIRTUAL_CPUID','FK_NARROW','LO8','LO16','HI8','SET_LO8','SET_LO16','SET_HI8','BSWAP32',
        'CMP_EQ','CMP_NE','CMP_B','CMP_BE','CMP_A','CMP_AE','CMP_L','CMP_LE','CMP_G','CMP_GE','CMP_S','CMP_NS',
        'TEST_Z','TEST_NZ','TEST_S','TEST_NS','TEST_G','TEST_LE'}
# Deliberately absent: CMP_O/CMP_NO/CMP_P/CMP_NP are TODO stubs in PCRecomp (constant results), so jo/jno/jp/jnp abort.
CPUID='CPUID(eax, ebx, ecx, edx);'
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

def lift_closure(roots,stop,imports,name,max_functions=64,indirect=False,follow_code_pointers=False,auto_stop=False):
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
    order=[];pending=list(roots);graph={};pointers=set()
    text=[x for x in pe.sections if x.Name.rstrip(b'\0')==b'.text'][0];text_start=base+text.VirtualAddress;text_end=text_start+text.Misc_VirtualSize
    while pending:
        address=pending.pop(0)
        if address in graph or address in stop:continue
        func=dis.disassemble_function(address,iat)
        if not func:raise SystemExit(f'no function at {address:#x}')
        graph[address]=func;order.append(address)
        if len(order)>max_functions:raise SystemExit('closure larger than allowed; add stop points')
        pending.extend(sorted(func.calls_to))
        if follow_code_pointers:
            # Function addresses used as immediates (e.g. constructors passed to the
            # array-constructor iterator) may be called indirectly: include them.
            for ins in (i for b in func.blocks.values() for i in b.instructions):
                operand=ins.op_str.split(',')[-1].strip()
                if ins.mnemonic in ('push','mov') and operand.startswith('0x'):
                    value=int(operand,16)
                    if text_start<=value<text_end and value not in graph and value not in stop and dis.disassemble_function(value,iat):
                        pointers.add(value);pending.append(value)
    sources=[];items=[];used_imports=set();stopped={}
    def translate(address):
        func=graph[address];instructions=[i for b in func.blocks.values() for i in b.instructions]
        start=min(i.address for i in instructions);end=max(i.address+i.size for i in instructions)
        if start!=address or end-start>0x2000:raise SystemExit(f'unexpected range at {address:#x}')
        source=Lifter(iat_map=iat).lift_function(func)
        if 'RECOMP_TODO' in source:raise SystemExit(f'unsupported instruction at {address:#x}')
        lifted=hashlib.sha256(source.encode()).hexdigest();sites=[];rewrites=[];used=set()
        def direct(m):
            target=int(m.group(1),16);site=int(m.group(2),16)
            if target!=int(m.group(3),16) or target not in func.calls_to:raise SystemExit(f'call target mismatch at {site:#x}')
            ins=list(decoder.disasm(pe.get_data(site-base,5),site,count=1))
            if len(ins)!=1 or ins[0].mnemonic!='call' or ins[0].size!=5 or int(ins[0].op_str,16)!=target:raise SystemExit(f'call decoding mismatch at {site:#x}')
            sites.append({'call':hex(site),'target':hex(target),'return':hex(site+5)})
            return f'MH_RECOMP_CALL_AT(sub_{target:08X}, 0x{site+5:08X}u);'
        def indirect_import(m):
            slot=int(m.group(1),16);site=int(m.group(2),16)
            if slot!=int(m.group(3),16) or slot not in imports:raise SystemExit(f'indirect call through {slot:#x} at {site:#x} is not an allowed import')
            ins=list(decoder.disasm(pe.get_data(site-base,6),site,count=1))
            if len(ins)!=1 or ins[0].mnemonic!='call' or ins[0].size!=6 or ins[0].bytes[:2]!=b'\xff\x15':raise SystemExit(f'import call decoding mismatch at {site:#x}')
            used.add(slot);sites.append({'call':hex(site),'import':names[slot],'slot':hex(slot),'return':hex(site+6)})
            return f'MH_RECOMP_ICALL_AT(MEM32(0x{slot:X}), 0x{site+6:08X}u);'
        def stos(m):
            rewrites.append('rep stos '+m.group(2).split(':')[0])
            return (f'{{ uint32_t _n = ecx, _b = _n * {m.group(1)}u; /* {m.group(2)} (checked) */ mh_recomp_rep_stos(edi, eax, _n, {m.group(1)}u, _df); '
                    'if (_df > 0) edi += _b; else edi -= _b; ecx = 0; }')
        def dynamic(m):
            # Any other call through a register or memory operand: fail-closed dispatch
            # through the generated table of translated functions, with its exact return.
            expr=m.group(1);site=int(m.group(2),16)
            if not indirect:raise SystemExit(f'indirect call at {site:#x} not allowed for this unit')
            slot=re.fullmatch(r'MEM32\(0x([0-9A-F]+)\)',expr)
            if slot and int(slot.group(1),16) in names:raise SystemExit(f'import call at {site:#x} not in the allowed list')
            ins=list(decoder.disasm(pe.get_data(site-base,8),site,count=1))
            if len(ins)!=1 or ins[0].mnemonic!='call' or ins[0].bytes[0]!=0xff:raise SystemExit(f'indirect call decoding mismatch at {site:#x}')
            sites.append({'call':hex(site),'indirect':ins[0].op_str,'return':hex(site+ins[0].size)})
            return f'MH_RECOMP_ICALL_AT({expr}, 0x{site+ins[0].size:08X}u);'
        source=CALL.sub(direct,source);source=ICALL.sub(indirect_import,source)
        source=re.sub(r'RECOMP_ICALL\(([^;]*?)\); /\* 0x([0-9A-F]{8}): call [^*]*\*/',dynamic,source)
        source=STOS.sub(stos,source)
        source,n=re.subn(r'\brecomp_rep_movs\(','mh_recomp_rep_movs(',source)
        if n:rewrites.append(f'{n} rep movs')
        n=source.count(CPUID)
        if n:source=source.replace(CPUID,'MH_VIRTUAL_CPUID();');rewrites.append(f'{n} cpuid -> virtual CPU')
        code_only=re.sub(r'/\*.*?\*/','',source,flags=re.DOTALL)  # validate code, not PCRecomp's comments
        left=re.findall(r'\bADDR\(|\bmemset\(|\bmemcpy\(|MEMSET\d*\(|RECOMP_CALL\(|RECOMP_ICALL\(|RECOMP_JMP\w*|\bfp_\w+\(|\b_st\[|\bg_st\b',code_only)
        if left:raise SystemExit(f'unsupported or unchecked construct left at {address:#x}: '+', '.join(sorted(set(left))))
        macros=set(re.findall(r'\b([A-Z][A-Z0-9_]+)\s*\(',code_only))-MACROS
        if macros:raise SystemExit(f'macros outside the audited list at {address:#x}: '+','.join(sorted(macros)))
        helpers=set(re.findall(r'\b(recomp_\w+)\s*\(',code_only))
        if not helpers.issubset(PURE_HELPERS):raise SystemExit(f'unchecked runtime helpers at {address:#x}: '+','.join(sorted(helpers-PURE_HELPERS)))
        operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',code_only))
        if not operations.issubset(ALLOWED):raise SystemExit(f'unsupported operations at {address:#x}: '+','.join(sorted(operations-ALLOWED)))
        return source,dict({'address':hex(address),'instructions':len(instructions),'range':[hex(start),hex(end)],
                      'bytes_sha256':hashlib.sha256(pe.get_data(start-base,end-start)).hexdigest(),'lifted_sha256':lifted,
                      'sites':sites,'rewrites':rewrites,'operations':sorted(operations)}),used

    for address in order:
        try:
            source,item,used=translate(address)
        except SystemExit as exc:
            # With auto_stop, a function that fails the audit becomes a stop point:
            # direct calls reach a fail-closed stub, indirect ones fail in dispatch.
            if not auto_stop or address in roots:raise
            stopped[address]=str(exc);continue
        sources.append(source);items.append(item);used_imports|=used
    lifted=[a for a in order if a not in stopped]
    declared=set(lifted)|{int(s['target'],16) for i in items for s in i['sites'] if 'target' in s}
    header=''.join(f'void sub_{a:08X}(void);\n' for a in sorted(declared))
    unit=header+'\n'.join(sources)+'\n'
    # Fail-closed dispatch table for indirect calls: translated functions only.
    table=sorted(lifted)
    dispatch=('/* Generated by tools/recomp_lift.py; private. Sorted VA -> translated function. */\n'
              f'static const uint32_t {name}_dispatch_va[{len(table)}]={{'+','.join(f'0x{a:x}u' for a in table)+'};\n'
              f'static void (*const {name}_dispatch_fn[{len(table)}])(void)={{'+','.join(f'sub_{a:08X}' for a in table)+'};\n'
              f'static recomp_func_t {name}_dispatch(uint32_t va){{size_t lo=0,hi={len(table)};'
              f'while(lo<hi){{size_t mid=(lo+hi)/2;if({name}_dispatch_va[mid]<va)lo=mid+1;else hi=mid;}}'
              f'return lo<{len(table)}&&{name}_dispatch_va[lo]==va?{name}_dispatch_fn[lo]:NULL;}}\n')
    out=ROOT/'private/analysis'/name;out.mkdir(parents=True,exist_ok=True)
    (out/f'{name}_unit.c').write_text(unit,encoding='utf-8',newline='\n')
    (out/f'{name}_dispatch.h').write_text(dispatch,encoding='utf-8',newline='\n')
    # Fail-closed stubs for functions referenced but not translated (stop points).
    unresolved=sorted(declared-set(lifted))
    (out/f'{name}_unresolved.h').write_text('/* Generated by tools/recomp_lift.py; private. Reaching one of these is an error. */\n'
        +''.join(f'void sub_{a:08X}(void){{mh_dispatch_fault(0x{a:x}u,g_cur_func);abort();}}\n' for a in unresolved),encoding='utf-8',newline='\n')
    report={'input_sha256':EXPECTED,'pcrecomp_revision':REVISION,'roots':[hex(r) for r in roots],'stop':[hex(s) for s in sorted(stop)],
            'imports':{hex(s):names[s] for s in sorted(used_imports)},'code_pointers':[hex(a) for a in sorted(pointers)],'unresolved':[hex(a) for a in unresolved],'auto_stopped':{hex(a):why for a,why in sorted(stopped.items())},'items':items,'unit_sha256':hashlib.sha256(unit.encode()).hexdigest()}
    (out/f'{name}_report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report
