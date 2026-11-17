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
With x87=True, x87 code is admitted through audited rewrites (_x87_rewrite):
typed raw accesses become checked MEMF/MEMD, arithmetic, fsqrt and fistp go
through recomp/x87_semantics.h, and only a closed list of PCRecomp x87 stack
helpers may remain. `dispatch_slots` are non-import memory slots whose calls
are dispatched by their run-time value (the protection's .prus slot). `provided` lists call targets the harness/runtime
implements (e.g. the header-stub replacement): no fail-closed stub for them.
The executable hash and the PCRecomp revision are verified first; output and
report go to private/analysis/<name>/ and are never published.
"""
import hashlib,json,re,sys
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,PCRECOMP,EXPECTED,REVISION
ALLOWED={'MEM8','MEM16','MEM32','PUSH32','POP32_VAL','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT'}
PURE_HELPERS={'recomp_flags_pack','recomp_eflags','recomp_eflags_setcf','recomp_flags_adc','recomp_flags_sbb'}  # pure functions of their arguments
# Closed list of macros allowed in translated code; any other uppercase macro call aborts.
MACROS={'MEM8','MEM16','MEM32','PUSH32','POP32_VAL','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT',
        'MH_RECOMP_CALL_AT','MH_RECOMP_ICALL_AT','MH_RECOMP_IJMP_AT','MH_VIRTUAL_CPUID','FK_NARROW','LO8','LO16','HI8','SET_LO8','SET_LO16','SET_HI8','BSWAP32',
        'CMP_EQ','CMP_NE','CMP_B','CMP_BE','CMP_A','CMP_AE','CMP_L','CMP_LE','CMP_G','CMP_GE','CMP_S','CMP_NS',
        'TEST_Z','TEST_NZ','TEST_S','TEST_NS','TEST_G','TEST_LE'}
# Deliberately absent: CMP_O/CMP_NO/CMP_P/CMP_NP are TODO stubs in PCRecomp (constant results), so jo/jno/jp/jnp abort.
CPUID='CPUID(eax, ebx, ecx, edx);'
CALL=re.compile(r'RECOMP_CALL\(sub_([0-9A-F]{8})\); /\* 0x([0-9A-F]{8}): call 0x([0-9a-f]+) \*/')
ICALL=re.compile(r'RECOMP_ICALL\(MEM32\(0x([0-9A-F]+)\)\); /\* 0x([0-9A-F]{8}): call dword ptr \[0x([0-9a-f]+)\] \*/')
STOS=re.compile(r'\{ uint32_t _n = ecx, _b = _n \* ([124])u; /\* (0x[0-9A-F]{8}: rep stos[bwd] [^*]*?) \*/ '
                r'if \(_df > 0\) \{ (?:memset|MEMSET16|MEMSET32)\(\(void\*\)ADDR\(edi\), (?:LO8\(eax\)|LO16\(eax\)|eax), _n\); edi \+= _b; \} '
                r'else \{ (?:memset|MEMSET16|MEMSET32)\(\(void\*\)ADDR\(edi - _b \+ \1u\), (?:LO8\(eax\)|LO16\(eax\)|eax), _n\); edi -= _b; \} ecx = 0; \}')

X87_HELPERS={'fp_push','fp_pop','fp_push_i64','fp_round_cw'}
X87_OPS={'+':'mh_x87_add','-':'mh_x87_sub','*':'mh_x87_mul','/':'mh_x87_div'}
X87_LIBM=re.compile(r'\b(sqrt|fabs|floor|ceil|trunc|nearbyint|rint|round|fmod|pow|ldexp|frexp|log\w*|exp\w*|sin|cos|tan|atan\w*|fp_\w+)\s*\(')
X87_ARITH_LEFT=re.compile(r'_st\[\d\]\s*[-+*/]=|[-+*/]\s*(?:\(double\)\s*)?_st\[|_st\[\d\]\s*[-+*/](?!=)|\b_v\s*[-+*/]|[-+*/]\s*_v\b')
def _x87_rewrite(source,address):
    """Audited rewrites of PCRecomp's x87 output. Returns (source, {rewrite: count})."""
    counts={}
    def count(key,n):
        if n:counts[key]=counts.get(key,0)+n
    for old,new in (('*(float*)ADDR(','MEMF('),('*(double*)ADDR(','MEMD('),('*(float*)&MEM32(','MEMF('),('*(double*)&MEM64(','MEMD(')):
        count('checked float access',source.count(old));source=source.replace(old,new)
    # st(i) op= rhs  ->  st(i) = helper(st(i), rhs)
    source,n=re.subn(r'_st\[(\d)\] ([-+*/])= ([^;]+);',lambda m:f'_st[{m.group(1)}] = {X87_OPS[m.group(2)]}(_st[{m.group(1)}], {m.group(3)});',source)
    count('x87 arithmetic',n)
    # reverse forms (fsubr/fdivr): st(i) = rhs op st(i)
    def reverse(m):
        if m.group(1)!=m.group(4):raise SystemExit(f'unexpected reverse x87 form at {address:#x}')
        return f'_st[{m.group(1)}] = {X87_OPS[m.group(3)]}({m.group(2)}, _st[{m.group(4)}]);'
    source,n=re.subn(r'_st\[(\d)\] = ([^;=]+?) ([-/]) _st\[(\d)\];',reverse,source);count('x87 reverse arithmetic',n)
    source,n=re.subn(r'\bsqrt\(_st\[0\]\)','mh_x87_sqrt(_st[0])',source);count('fsqrt',n)
    source,n=re.subn(r'\bfp_st0_to_i64\(','mh_x87_st0_to_i64(',source);count('fistp qword',n)
    code=re.sub(r'/\*.*?\*/','',source,flags=re.DOTALL)
    if X87_ARITH_LEFT.search(code):raise SystemExit(f'x87 arithmetic left without helper at {address:#x}')
    left={m.group(1) for m in X87_LIBM.finditer(code)}-X87_HELPERS
    if left:raise SystemExit(f'unaudited x87/libm calls at {address:#x}: '+','.join(sorted(left)))
    if re.search(r'\(float\*\)|\(double\*\)|\bADDR\(',code):raise SystemExit(f'unchecked float access left at {address:#x}')
    return source,counts

def _tools():
    for part in ('pe','disasm','lift'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from pe_analyze import analyze_pe,build_iat_map
    from disasm32 import Disassembler
    from lift32 import Lifter
    return analyze_pe,build_iat_map,Disassembler,Lifter

def lift_closure(roots,stop,imports,name,max_functions=64,indirect=False,follow_code_pointers=False,auto_stop=False,x87=False,provided=(),dispatch_slots=()):
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
            if target!=int(m.group(3),16) or (target not in func.calls_to and target not in provided):raise SystemExit(f'call target mismatch at {site:#x}')
            ins=list(decoder.disasm(pe.get_data(site-base,5),site,count=1))
            if len(ins)!=1 or ins[0].mnemonic!='call' or ins[0].size!=5 or int(ins[0].op_str,16)!=target:raise SystemExit(f'call decoding mismatch at {site:#x}')
            sites.append({'call':hex(site),'target':hex(target),'return':hex(site+5)})
            return f'MH_RECOMP_CALL_AT(sub_{target:08X}, 0x{site+5:08X}u);'
        def indirect_import(m):
            slot=int(m.group(1),16);site=int(m.group(2),16)
            if slot!=int(m.group(3),16) or (slot not in imports and slot not in dispatch_slots):raise SystemExit(f'indirect call through {slot:#x} at {site:#x} is not an allowed import')
            ins=list(decoder.disasm(pe.get_data(site-base,6),site,count=1))
            if len(ins)!=1 or ins[0].mnemonic!='call' or ins[0].size!=6 or ins[0].bytes[:2]!=b'\xff\x15':raise SystemExit(f'import call decoding mismatch at {site:#x}')
            if slot in dispatch_slots:  # dispatched by the slot's run-time value, with the exact return address
                sites.append({'call':hex(site),'slot':hex(slot),'dispatch':True,'return':hex(site+6)})
                return f'MH_RECOMP_ICALL_AT(MEM32(0x{slot:X}), 0x{site+6:08X}u);'
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
        def import_jump(m):
            slot=int(m.group(1),16);site=int(m.group(2),16)
            if slot!=int(m.group(3),16) or slot not in imports:raise SystemExit(f'jump through {slot:#x} at {site:#x} is not an allowed import')
            ins=list(decoder.disasm(pe.get_data(site-base,6),site,count=1))
            if len(ins)!=1 or ins[0].mnemonic!='jmp' or ins[0].size!=6 or ins[0].bytes[:2]!=b'\xff\x25':raise SystemExit(f'import jump decoding mismatch at {site:#x}')
            used.add(slot);sites.append({'jump':hex(site),'import':names[slot],'slot':hex(slot)})
            return f'MH_RECOMP_IJMP_AT(MEM32(0x{slot:X})); return;'
        source=CALL.sub(direct,source);source=ICALL.sub(indirect_import,source)
        source=re.sub(r'RECOMP_ITAIL\(MEM32\(0x([0-9A-F]+)\)\); return; /\* 0x([0-9A-F]{8}): jmp dword ptr \[0x([0-9a-f]+)\] \*/',import_jump,source)
        source=re.sub(r'RECOMP_ICALL\(([^;]*?)\); /\* 0x([0-9A-F]{8}): call [^*]*\*/',dynamic,source)
        source=STOS.sub(stos,source)
        source,n=re.subn(r'\brecomp_rep_movs\(','mh_recomp_rep_movs(',source)
        if n:rewrites.append(f'{n} rep movs')
        n=source.count(CPUID)
        if n:source=source.replace(CPUID,'MH_VIRTUAL_CPUID();');rewrites.append(f'{n} cpuid -> virtual CPU')
        if x87:
            source,counts=_x87_rewrite(source,address)
            rewrites.extend(f'{v} {k}' for k,v in counts.items())
        code_only=re.sub(r'/\*.*?\*/','',source,flags=re.DOTALL)  # validate code, not PCRecomp's comments
        forbidden=r'\bADDR\(|\bmemset\(|\bmemcpy\(|MEMSET\d*\(|RECOMP_CALL\(|RECOMP_ICALL\(|RECOMP_JMP\w*'+('' if x87 else r'|\bfp_\w+\(|\b_st\[|\bg_st\b')
        left=re.findall(forbidden,code_only)
        if left:raise SystemExit(f'unsupported or unchecked construct left at {address:#x}: '+', '.join(sorted(set(left))))
        macros=set(re.findall(r'\b([A-Z][A-Z0-9_]+)\s*\(',code_only))-MACROS-({'MEMF','MEMD','MEM64','FPU_CMP'} if x87 else set())
        if macros:raise SystemExit(f'macros outside the audited list at {address:#x}: '+','.join(sorted(macros)))
        helpers=set(re.findall(r'\b(recomp_\w+)\s*\(',code_only))
        if not helpers.issubset(PURE_HELPERS):raise SystemExit(f'unchecked runtime helpers at {address:#x}: '+','.join(sorted(helpers-PURE_HELPERS)))
        operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',code_only))
        if not operations.issubset(ALLOWED|({'MEMF','MEMD','MEM64'} if x87 else set())):raise SystemExit(f'unsupported operations at {address:#x}: '+','.join(sorted(operations-ALLOWED)))
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
    unresolved=sorted(declared-set(lifted)-set(provided))
    (out/f'{name}_unresolved.h').write_text('/* Generated by tools/recomp_lift.py; private. Reaching one of these is an error. */\n'
        +''.join(f'void sub_{a:08X}(void){{mh_dispatch_fault(0x{a:x}u,g_cur_func);abort();}}\n' for a in unresolved),encoding='utf-8',newline='\n')
    report={'input_sha256':EXPECTED,'pcrecomp_revision':REVISION,'roots':[hex(r) for r in roots],'stop':[hex(s) for s in sorted(stop)],
            'imports':{hex(s):names[s] for s in sorted(used_imports)},'code_pointers':[hex(a) for a in sorted(pointers)],'unresolved':[hex(a) for a in unresolved],'provided':[hex(a) for a in sorted(provided)],'x87':x87,'auto_stopped':{hex(a):why for a,why in sorted(stopped.items())},'items':items,'unit_sha256':hashlib.sha256(unit.encode()).hexdigest()}
    (out/f'{name}_report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report
