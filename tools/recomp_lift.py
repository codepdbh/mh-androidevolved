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
PURE_HELPERS={'recomp_flags_pack','recomp_eflags','recomp_eflags_setcf','recomp_flags_adc','recomp_flags_sbb','recomp_cond','recomp_carry','recomp_cond_cf','recomp_parity8'}  # pure functions of their arguments (checked: no globals, no memory)
# Closed list of macros allowed in translated code; any other uppercase macro call aborts.
MACROS={'MEM8','MEM16','MEM32','PUSH32','POP32_VAL','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT',
        'MH_RECOMP_CALL_AT','MH_RECOMP_ICALL_AT','MH_RECOMP_IJMP_AT','MH_VIRTUAL_CPUID','FK_NARROW','LO8','LO16','HI8','SET_LO8','SET_LO16','SET_HI8','BSWAP32',
        'CMP_EQ','CMP_NE','CMP_B','CMP_BE','CMP_A','CMP_AE','CMP_L','CMP_LE','CMP_G','CMP_GE','CMP_S','CMP_NS',
        'TEST_Z','TEST_NZ','TEST_S','TEST_NS','TEST_G','TEST_LE','RECOMP_PF'}   # RECOMP_PF: parity of the result's low byte (x86 PF)
# Deliberately absent: CMP_O/CMP_NO/CMP_P/CMP_NP are TODO stubs in PCRecomp (constant results), so jo/jno/jp/jnp abort.
CPUID='CPUID(eax, ebx, ecx, edx);'
CALL=re.compile(r'RECOMP_CALL\(sub_([0-9A-F]{8})\); /\* 0x([0-9A-F]{8}): call 0x([0-9a-f]+) \*/')
ICALL=re.compile(r'RECOMP_ICALL\(MEM32\(0x([0-9A-F]+)\)\); /\* 0x([0-9A-F]{8}): call dword ptr \[0x([0-9a-f]+)\] \*/')
STOS=re.compile(r'\{ uint32_t _n = ecx, _b = _n \* ([124])u; /\* (0x[0-9A-F]{8}: rep stos[bwd] [^*]*?) \*/ '
                r'if \(_df > 0\) \{ (?:memset|MEMSET16|MEMSET32)\(\(void\*\)ADDR\(edi\), (?:LO8\(eax\)|LO16\(eax\)|eax), _n\); edi \+= _b; \} '
                r'else \{ (?:memset|MEMSET16|MEMSET32)\(\(void\*\)ADDR\(edi - _b \+ \1u\), (?:LO8\(eax\)|LO16\(eax\)|eax), _n\); edi -= _b; \} ecx = 0; \}')

# Host functions translated code may call (besides sub_*, pure recomp_* helpers and, in x87 mode,
# mh_x87_* and the x87 stack helpers): audited memory/dispatch helpers and the port's counters.
HOST_CALLS={'mh_recomp_rep_stos','mh_recomp_rep_movs','mh_recomp_access','mh_dispatch_fault','abort','mh_x86_daa','mh_guest_rdtsc','mh_x87_bld'}
X87_HELPERS={'fp_push','fp_pop','fp_push_i64','fp_round_cw','fp_xch','fabs'}
X87_OPS={'+':'mh_x87_add_pc','-':'mh_x87_sub_pc','*':'mh_x87_mul_pc','/':'mh_x87_div_pc'}   # rounded to the control word's precision
X87_LIBM=re.compile(r'\b(sqrt|fabs|floor|ceil|trunc|nearbyint|rint|round|fmod|pow|ldexp|frexp|log\w*|exp\w*|sin|cos|tan|atan\w*|fp_\w+)\s*\(')
X87_ARITH_LEFT=re.compile(r'_st\[\d\]\s*[-+*/]=|[-+*/]\s*(?:\(double\)\s*)?_st\[|_st\[\d\]\s*[-+*/](?!=)|\b_v\s*[-+*/]|[-+*/]\s*_v\b')
def _x87_rewrite(source,address):
    """Audited rewrites of PCRecomp's x87 output. Returns (source, {rewrite: count})."""
    counts={}
    def count(key,n):
        if n:counts[key]=counts.get(key,0)+n
    # fld/fstp tbyte: 10 checked bytes and exact NaN/infinity conversion
    source,n=re.subn(r'fp_push\(fp_ld80\(\(const uint8_t\*\)ADDR\(([^;]*?)\)\)\);',r'fp_push(mh_x87_ld80((const uint8_t*)mh_recomp_access((uint32_t)(\1), 10)));',source);count('fld tbyte',n)
    source,n=re.subn(r'fp_st80\(\(uint8_t\*\)ADDR\(([^;]*?)\), fp_pop\(\)\);',r'mh_x87_st80((uint8_t*)mh_recomp_access((uint32_t)(\1), 10), fp_pop());',source);count('fstp tbyte',n)
    for old,new in (('*(float*)ADDR(','MEMF('),('*(double*)ADDR(','MEMD('),('*(float*)&MEM32(','MEMF('),('*(double*)&MEM64(','MEMD(')):
        count('checked float access',source.count(old));source=source.replace(old,new)
    # Transcendental and special forms, exactly as lift32.py emits them (before the generic
    # arithmetic rule, which would otherwise take `*= log(...)` for a multiplication).
    special=(
        ('{ double _x = fp_pop(); _st[0] *= log(_x) / 0.6931471805599453; }','{ double _x = fp_pop(); _st[0] = mh_x87_yl2x(_st[0], _x); }','fyl2x'),
        ('{ double _x = fp_pop(); _st[0] *= log(_x + 1.0) / 0.6931471805599453; }','{ double _x = fp_pop(); _st[0] = mh_x87_yl2xp1(_st[0], _x); }','fyl2xp1'),
        ('_st[0] = pow(2.0, _st[0]) - 1.0;','_st[0] = mh_x87_f2xm1(_st[0]);','f2xm1'),
        ('_st[0] *= pow(2.0, (double)(int)_st[1]);','_st[0] = mh_x87_scale(_st[0], _st[1]);','fscale'),
        ('_st[0] = fmod(_st[0], _st[1]);','_st[0] = mh_x87_fmod(_st[0], _st[1]);','fprem'),
        ('{ double _x = fp_pop(); _st[0] = atan2(_st[0], _x); }','{ double _x = fp_pop(); _st[0] = mh_x87_atan2(_st[0], _x); }','fpatan'),
        ('_st[0] = -_st[0];','_st[0] = mh_x87_chs(_st[0]);','fchs'),
        ('_st[0] = sin(_st[0]);','_st[0] = mh_x87_sin(_st[0]);','fsin'),
        ('_st[0] = cos(_st[0]);','_st[0] = mh_x87_cos(_st[0]);','fcos'),
        ('_st[0] = tan(_st[0]); fp_push(1.0);','_st[0] = mh_x87_tan(_st[0]); fp_push(1.0);','fptan'),
        ('{ double _a = _st[0]; _st[0] = sin(_a); fp_push(cos(_a)); }','{ double _a = _st[0]; _st[0] = mh_x87_sin(_a); fp_push(mh_x87_cos(_a)); }','fsincos'))
    for old,new,label in special:
        count(label,source.count(old));source=source.replace(old,new)
    # fdivp/fdivrp: PCRecomp guards a zero divisor by keeping the operand; x87 (exceptions masked)
    # gives a signed infinity, or the indefinite for 0/0 -- IEEE division through the helper.
    source,n=re.subn(r'\{ double _v = fp_pop\(\); (_st\[\d\]) = _v == 0\.0 \? \1 : \1 / _v; \}',r'{ double _v = fp_pop(); \1 = mh_x87_div_pc(\1, _v, _fpu_cw); }',source);count('fdivp',n)
    source,n=re.subn(r'\{ double _v = fp_pop\(\); (_st\[\d\]) = \1 == 0\.0 \? _v : _v / \1; \}',r'{ double _v = fp_pop(); \1 = mh_x87_div_pc(_v, \1, _fpu_cw); }',source);count('fdivrp',n)
    # fist/fistp word and dword: integer indefinite instead of C's undefined conversion
    source,n=re.subn(r'\(uint32_t\)\(int32_t\)fp_to_int\(([^;]*?)\);',r'(uint32_t)mh_x87_to_i32(\1, _fpu_cw);',source);count('fist dword',n)
    source,n=re.subn(r'\(int16_t\)fp_to_int\(([^;]*?)\);',r'(uint16_t)mh_x87_to_i16(\1, _fpu_cw);',source);count('fist word',n)
    # st(i) op= rhs  ->  st(i) = helper(st(i), rhs)
    source,n=re.subn(r'_st\[(\d)\] ([-+*/])= ([^;]+);',lambda m:f'_st[{m.group(1)}] = {X87_OPS[m.group(2)]}(_st[{m.group(1)}], {m.group(3)}, _fpu_cw);',source)
    count('x87 arithmetic',n)
    # integer-operand forms (fimul/fiadd/fisub/fidiv): st(i) = st(i) op rhs
    source,n=re.subn(r'_st\[(\d)\] = _st\[\1\] ([-+*/]) ([^;]+);',lambda m:f'_st[{m.group(1)}] = {X87_OPS[m.group(2)]}(_st[{m.group(1)}], {m.group(3)}, _fpu_cw);',source)
    count('x87 integer-operand arithmetic',n)
    # reverse forms (fsubr/fdivr): st(i) = rhs op st(i)
    def reverse(m):
        if m.group(1)!=m.group(4):raise SystemExit(f'unexpected reverse x87 form at {address:#x}')
        return f'_st[{m.group(1)}] = {X87_OPS[m.group(3)]}({m.group(2)}, _st[{m.group(4)}], _fpu_cw);'
    source,n=re.subn(r'_st\[(\d)\] = ([^;=]+?) ([-/]) _st\[(\d)\];',reverse,source);count('x87 reverse arithmetic',n)
    source,n=re.subn(r'\bsqrt\(_st\[0\]\)','mh_x87_sqrt_pc(_st[0], _fpu_cw)',source);count('fsqrt',n)
    source,n=re.subn(r'\bfp_st0_to_i64\(','mh_x87_st0_to_i64(',source);count('fistp qword',n)
    code=re.sub(r'/\*.*?\*/','',source,flags=re.DOTALL)
    if X87_ARITH_LEFT.search(code):raise SystemExit(f'x87 arithmetic left without helper at {address:#x}')
    left={m.group(1) for m in X87_LIBM.finditer(code)}-X87_HELPERS
    if left:raise SystemExit(f'unaudited x87/libm calls at {address:#x}: '+','.join(sorted(left)))
    if re.search(r'\(float\*\)|\(double\*\)|\bADDR\(',code):raise SystemExit(f'unchecked float access left at {address:#x}')
    return source,counts

def switch_bound(read,address):
    """Number of entries of the jump table dispatched by the `jmp [table + idx*4]` at `address`,
    from its guard: the last `cmp idx, N` followed by `ja` (N+1 entries) or `jae` (N entries)
    among the few instructions before it, with no later write to idx. None when absent."""
    decoder=Cs(CS_ARCH_X86,CS_MODE_32)
    # The guard may lie some way back (x87 code in between): try every decoding alignment that
    # reaches the jump and keep the first that shows a valid guard.
    found=set()
    for back in range(0x40,0,-1):
        ins=list(decoder.disasm(read(address-back,back+8),address-back))
        if any(i.address==address for i in ins):
            n=_switch_guard(ins,address)
            k=next(j for j,i in enumerate(ins) if i.address==address)
            low={'eax':'al','ebx':'bl','ecx':'cl','edx':'dl'}
            r=ins[k].op_str[len('dword ptr ['):].split('*')[0] if ins[k].op_str.startswith('dword ptr [') else ''
            if n is None and k>=2 and r in low and ins[k-2].mnemonic=='xor' and ins[k-2].op_str==f'{r}, {r}' and ins[k-1].mnemonic=='mov':
                # two-level switch: a byte table indexed by i (bounded by its own guard) selects the entry
                m=re.fullmatch(low[r]+r', byte ptr \[(e[a-z]{2}) \+ 0x([0-9a-f]+)\]',ins[k-1].op_str)
                if m:
                    inner=_switch_guard(ins[:k-2]+[_Fake(ins[k-2].address,'jmp',f'dword ptr [{m.group(1)}*4 + 0x0]')],ins[k-2].address)
                    if inner:n=max(read(int(m.group(2),16),inner))+1
            if n is not None:found.add(n)
    return found.pop() if len(found)==1 else None   # every alignment that shows a guard must agree
class _Fake:
    def __init__(self,address,mnemonic,op_str):self.address,self.mnemonic,self.op_str=address,mnemonic,op_str
def _switch_guard(ins,address):
    k=next(j for j,i in enumerate(ins) if i.address==address)
    jmp=ins[k];idx=jmp.op_str.split('[')[1].split('*')[0].strip()
    for j in range(k-1,max(k-8,0),-1):
        i=ins[j]
        if i.mnemonic in('ja','jae'):
            # the flags come from the nearest cmp before it; flag-neutral moves in between must not write idx
            c=j-1
            # x87 loads/stores/arithmetic leave EFLAGS and the integer registers alone (not fcomi/fucomi, which set
            # EFLAGS, nor fnstsw, which writes ax)
            neutral=lambda m:m in('mov','lea','movzx','movsx','push','pop') or (m.startswith('f') and not m.startswith(('fcomi','fucomi','fnstsw','fstsw')))
            while c>0 and neutral(ins[c].mnemonic) and ins[c].op_str.split(',')[0].strip()!=idx:c-=1
            if ins[c].mnemonic=='test' and i.mnemonic=='ja' and ins[c].op_str==f'{idx}, {idx}':return 1   # test leaves CF=0: ja exits unless idx==0
            if ins[c].mnemonic!='cmp':return None
            cmp=ins[c];reg,_,imm=cmp.op_str.partition(', ')
            if imm in ('eax','ebx','ecx','edx','esi','edi','ebp'):
                # `mov r, N` shortly before (r not written in between): the bound is N
                for b in range(c-1,max(c-6,-1),-1):
                    w=ins[b]
                    if w.op_str.split(',')[0].strip()!=imm or w.mnemonic in('push','cmp','test'):continue
                    imm=w.op_str.partition(', ')[2] if w.mnemonic=='mov' else '';break
                else:return None
            if reg!=idx or not imm.startswith(('0x','1','2','3','4','5','6','7','8','9')) or not imm.replace('0x','').isalnum():return None
            n=int(imm,0)+(1 if i.mnemonic=='ja' else 0)
            return n if 0<n<=1024 else None
        if i.op_str.split(',')[0].strip()==idx and i.mnemonic not in('cmp','test','push'):return None   # idx rewritten after the guard
    return None

def _tools():
    for part in ('pe','disasm','lift'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from pe_analyze import analyze_pe,build_iat_map
    import disasm32
    from disasm32 import Disassembler
    from lift32 import Lifter
    if not getattr(Disassembler,'_mh_bounded',False):
        # PCRecomp reads a jump table until the first non-code entry, so adjacent tables of
        # different switches merge and pull other functions' code in. Bound every table by its
        # guard instead and require all its entries to be code; no guard aborts the lift.
        def bounded(self,insn,limit=256):
            if not insn.operands:return []
            op=insn.operands[0]
            if op.type!=disasm32.X86_OP_MEM or op.mem.scale!=4 or not op.mem.index:return []
            n=switch_bound(self.read_bytes,insn.address)
            if n is None:raise SystemExit(f'jump table at {insn.address:#x} without a recognisable bound')
            table=op.mem.disp&0xFFFFFFFF;out=[]
            for k in range(n):
                tgt=int.from_bytes(self.read_bytes(table+4*k,4),'little')
                if not self.is_code_address(tgt):raise SystemExit(f'jump table {table:#x} entry {k} is not code ({tgt:#x})')
                out.append(tgt)
            return out
        Disassembler.jump_table_targets=bounded;Disassembler._mh_bounded=True
    return analyze_pe,build_iat_map,Disassembler,Lifter

def lift_closure(roots,stop,imports,name,max_functions=64,indirect=False,follow_code_pointers=False,auto_stop=False,x87=False,provided=(),dispatch_slots=()):
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    if (PCRECOMP/'REVISION.txt').read_text(encoding='ascii').strip()!=REVISION:raise SystemExit('unexpected tool revision')
    if not re.fullmatch(r'[a-z0-9_]{1,40}',name):raise SystemExit('invalid unit name')
    pe=pefile.PE(data=data);base=pe.OPTIONAL_HEADER.ImageBase;decoder=Cs(CS_ARCH_X86,CS_MODE_32)
    resume_sites={}
    redirects_path=ROOT/'private/analysis/protection/redirects.json'
    if dispatch_slots and redirects_path.exists():
        for s in json.loads(redirects_path.read_text(encoding='utf-8'))['slot_sites']:
            if s['kind']=='resume':resume_sites[int(s['return'],16)]=(int(s['value'],16),s['args'])
    names={}
    for entry in pe.DIRECTORY_ENTRY_IMPORT:
        for imp in entry.imports:names[imp.address]=imp.name.decode() if imp.name else f'ordinal_{imp.ordinal}'
    for slot in imports:
        if slot not in names:raise SystemExit(f'{slot:#x} is not an import slot')
    analyze_pe,build_iat_map,Disassembler,Lifter=_tools()
    info=analyze_pe(str(GAME));iat=build_iat_map(info);dis=Disassembler(data,info.image_base,info.sections)
    order=[];pending=list(roots);graph={};pointers=set();thunks={}
    text=[x for x in pe.sections if x.Name.rstrip(b'\0')==b'.text'][0];text_start=base+text.VirtualAddress;text_end=text_start+text.Misc_VirtualSize
    while pending:
        address=pending.pop(0)
        if address in graph or address in stop:continue
        # A thunk (`jmp rel` at the entry, e.g. 0x610f00 -> 0x610d40) is a tail jump to another
        # function, not part of its body: translate it as a call that the target returns from.
        entry=list(decoder.disasm(pe.get_data(address-base,5),address,count=1))
        if entry and entry[0].mnemonic=='jmp' and entry[0].bytes[0] in (0xe9,0xeb) and entry[0].op_str.startswith('0x'):
            target=int(entry[0].op_str,16)
            if target!=address and text_start<=target<text_end:
                thunks[address]=(target,entry[0]);graph[address]=None;order.append(address);pending.append(target);continue
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
        if address in thunks:
            target,ins=thunks[address]
            source=(f'void sub_{address:08X}(void) {{\n    g_cur_func = 0x{address:08X}u;\n'
                    f'    sub_{target:08X}(); /* 0x{address:08X}: jmp 0x{target:x} (thunk: tail jump, the target returns) */\n}}\n')
            return source,{'address':hex(address),'instructions':1,'range':[hex(address),hex(address+ins.size)],
                           'bytes_sha256':hashlib.sha256(bytes(ins.bytes)).hexdigest(),'lifted_sha256':hashlib.sha256(source.encode()).hexdigest(),
                           'sites':[{'jump':hex(address),'target':hex(target)}],'rewrites':['thunk'],'operations':[]},set()
        func=graph[address];instructions=[i for b in func.blocks.values() for i in b.instructions]
        start=min(i.address for i in instructions);end=max(i.address+i.size for i in instructions)
        # Jump tables are bounded (see _tools), so what PCRecomp merges into a function is code
        # reached by its own jumps: tail jumps into neighbouring functions are executed in line,
        # which is equivalent (same stack and registers). Large gaps or spans still mean an error.
        # Each separate stretch of code (split at gaps over 64 bytes) other than the entry's must
        # begin at the target of one of the function's unconditional jumps, i.e. be a tail jump;
        # a stretch starting anywhere else (e.g. at a misread switch arm) is rejected.
        spans=sorted({(i.address,i.address+i.size) for i in instructions})
        segments=[[spans[0][0],spans[0][1]]]
        for a0,a1 in spans[1:]:
            if a0-segments[-1][1]>64:segments.append([a0,a1])
            else:segments[-1][1]=max(segments[-1][1],a1)
        jumps={int(i.op_str,16) for i in instructions if i.mnemonic=='jmp' and i.op_str.startswith('0x')}
        stray=[hex(s0) for s0,s1 in segments if not s0<=address<s1 and s0 not in jumps]
        if address not in {i.address for i in instructions} or stray or end-start>0x100000:
            raise SystemExit(f'unexpected range at {address:#x} ({end-start:#x} bytes; stretches not reached by a jmp: {stray})')
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
            if slot!=int(m.group(3),16) or (slot not in imports and slot not in dispatch_slots and (slot in names or not indirect)):raise SystemExit(f'indirect call through {slot:#x} at {site:#x} is not an allowed import')
            ins=list(decoder.disasm(pe.get_data(site-base,6),site,count=1))
            if len(ins)!=1 or ins[0].mnemonic!='call' or ins[0].size!=6 or ins[0].bytes[:2]!=b'\xff\x15':raise SystemExit(f'import call decoding mismatch at {site:#x}')
            if slot in dispatch_slots and site+6 in resume_sites:
                # protection "resume" site (tools/resolve_protection_redirects.py): the intact wrapper drops its
                # stdcall arguments and continues at a label of this function, past the penalty code
                target,args=resume_sites[site+6]
                if not site<target<=site+0x40:raise SystemExit(f'resume target {target:#x} of {site:#x} out of range')
                sites.append({'call':hex(site),'slot':hex(slot),'resume':hex(target),'args':args})
                rewrites.append('protection resume')
                return f'esp += {4*args}u; goto L_{target:08X}; /* protection: continue past the penalty */'
            if slot in dispatch_slots or slot not in names:  # a slot or a global function pointer: dispatched by its run-time value, exact return address
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
            if slot!=int(m.group(3),16) or (slot not in imports and (slot in names or not indirect)):raise SystemExit(f'jump through {slot:#x} at {site:#x} is not an allowed import')
            ins=list(decoder.disasm(pe.get_data(site-base,6),site,count=1))
            if len(ins)!=1 or ins[0].mnemonic!='jmp' or ins[0].size!=6 or ins[0].bytes[:2]!=b'\xff\x25':raise SystemExit(f'import jump decoding mismatch at {site:#x}')
            if slot not in names:   # a global function pointer, dispatched by its run-time value
                sites.append({'jump':hex(site),'slot':hex(slot),'dispatch':True});return f'MH_RECOMP_IJMP_AT(MEM32(0x{slot:X})); return;'
            used.add(slot);sites.append({'jump':hex(site),'import':names[slot],'slot':hex(slot)})
            return f'MH_RECOMP_IJMP_AT(MEM32(0x{slot:X})); return;'
        source=CALL.sub(direct,source);source=ICALL.sub(indirect_import,source)
        source=re.sub(r'RECOMP_ITAIL\(MEM32\(0x([0-9A-F]+)\)\); return; /\* 0x([0-9A-F]{8}): jmp dword ptr \[0x([0-9a-f]+)\] \*/',import_jump,source)
        def indirect_jump(m):
            # `jmp reg` / `jmp [mem]` that is not a switch: a tail call through a vtable or pointer,
            # dispatched fail-closed with the caller's return address still on the stack.
            expr=m.group(1);site=int(m.group(2),16)
            if not indirect:raise SystemExit(f'indirect jump at {site:#x} not allowed for this unit')
            ins=list(decoder.disasm(pe.get_data(site-base,8),site,count=1))
            if len(ins)!=1 or ins[0].mnemonic!='jmp' or ins[0].bytes[0]!=0xff:raise SystemExit(f'indirect jump decoding mismatch at {site:#x}')
            sites.append({'jump':hex(site),'indirect':ins[0].op_str})
            return f'MH_RECOMP_IJMP_AT({expr}); return;'
        source=re.sub(r'RECOMP_ITAIL\(([^;]*?)\); return; /\* 0x([0-9A-F]{8}): jmp (?:(?!\*/).)*\*/',indirect_jump,source)   # operands may contain '*' (index*scale)
        source=re.sub(r'RECOMP_ICALL\(([^;]*?)\); /\* 0x([0-9A-F]{8}): call (?:(?!\*/).)*\*/',dynamic,source)
        source=STOS.sub(stos,source)
        # Instructions PCRecomp leaves as an empty statement (`; /* UNIMPLEMENTED: ... */`), with
        # their bytes checked; anything else still unimplemented aborts below.
        def unimplemented(m):
            mnem,ops,site=m.group(1),m.group(2).strip(),int(m.group(3),16)
            raw=pe.get_data(site-base,4)
            if mnem=='daa' and raw[0]==0x27:
                rewrites.append('daa')
                return (f'{{ uint32_t _e = mh_x86_daa(&eax, recomp_eflags(_flag_k, _flag_a, _flag_b, _cf, _df)); '
                        f'_flag_k = FK_EFLAGS; _flag_a = _e; _flag_b = 0; _cf = _e & 1u; }} /* 0x{site:08X}: daa */')
            if mnem=='pushf' and raw[:2]==b'\x66\x9c':   # 16-bit: pushes FLAGS (2 bytes)
                rewrites.append('pushf16')
                return f'esp = esp - 2u; MEM16(esp) = (uint16_t)recomp_eflags(_flag_k, _flag_a, _flag_b, _cf, _df); /* 0x{site:08X}: pushf */'
            if mnem=='popf' and raw[:2]==b'\x66\x9d':    # 16-bit: replaces the low half of EFLAGS
                rewrites.append('popf16')
                return (f'{{ uint32_t _fl = (recomp_eflags(_flag_k, _flag_a, _flag_b, _cf, _df) & 0xFFFF0000u) | MEM16(esp); esp = esp + 2u; '
                        f'_flag_k = FK_EFLAGS; _flag_a = _fl; _flag_b = 0; _cf = _fl & 1u; _df = (_fl & 0x400u) ? -1 : 1; }} /* 0x{site:08X}: popf */')
            mem=re.fullmatch(r'tbyte ptr \[([a-z0-9 +*x-]+)\]',ops)
            if mnem=='fbld' and mem and raw[0]==0xdf and (raw[1]>>3)&7==4:
                rewrites.append('fbld')
                return f'fp_push(mh_x87_bld((const uint8_t*)mh_recomp_access((uint32_t)({mem.group(1)}), 10))); /* 0x{site:08X}: fbld {ops} */'
            return m.group(0)
        source=re.sub(r'; /\* UNIMPLEMENTED: (\w+) ([^*]*?)\*/ /\* 0x([0-9A-F]{8}): [^*]*\*/',unimplemented,source)
        if 'UNIMPLEMENTED' in source:raise SystemExit(f'unimplemented instruction at {address:#x}: '+re.search(r'UNIMPLEMENTED: [^*]*',source).group(0))
        source,n=re.subn(r'\brecomp_rep_movs\(','mh_recomp_rep_movs(',source)
        if n:rewrites.append(f'{n} rep movs')
        # rdtsc: the guest's time-stamp counter comes from the port (deterministic), never the host's.
        n=source.count('uint64_t _t = __rdtsc();')
        if n:source=source.replace('uint64_t _t = __rdtsc();','uint64_t _t = mh_guest_rdtsc();');rewrites.append(f'{n} rdtsc -> port counter')
        n=source.count(CPUID)
        if n:source=source.replace(CPUID,'MH_VIRTUAL_CPUID();');rewrites.append(f'{n} cpuid -> virtual CPU')
        # Switches: the bounded table only holds this function's arms, so a value that is not one
        # of them is a fault, not a tail jump to an unknown address.
        source,n=re.subn(r'default: RECOMP_ITAIL\(_jt\); return;','default: mh_dispatch_fault(_jt, g_cur_func); abort();',source)
        if n:rewrites.append(f'{n} bounded switch')
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
        # Every other function the translated code calls must be on a closed list: translated
        # functions, audited port/x87 helpers and fault handlers (a host call such as __rdtsc
        # would make the result depend on the machine).
        calls=set(re.findall(r'\b([A-Za-z_]\w*)\s*\(',code_only))-MACROS-{'if','while','for','switch','return','sizeof'}
        host=sorted(c for c in calls if not (re.fullmatch(r'sub_[0-9A-F]{8}',c) or c in HOST_CALLS or c in PURE_HELPERS
                    or c in ALLOWED or c in {'RECOMP_PF','MEMF','MEMD','MEM64','FPU_CMP'} or (x87 and (c.startswith('mh_x87_') or c in X87_HELPERS))))
        if host:raise SystemExit(f'host functions called at {address:#x}: '+','.join(host))
        operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',code_only))
        allowed=ALLOWED|{'RECOMP_PF'}|({'MEMF','MEMD','MEM64'} if x87 else set())
        if not operations.issubset(allowed):raise SystemExit(f'unsupported operations at {address:#x}: '+','.join(sorted(operations-allowed)))
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
