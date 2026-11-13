"""Lift 0x5daa50 (x87 ratio update, three calls) and the getter 0x5ea2b0 to private C.

Two audited rewrites are applied to the generated code:
- the five `*(float*)ADDR(x)` accesses become bounds-checked `MEMF(x)`;
- PCRecomp's `fdivp` guard (returns st(1) unchanged on a zero divisor) is
  removed, and every x87 arithmetic operation goes through the helpers in
  recomp/x87_semantics.h: IEEE results (+-inf on a zero divisor) with the x87
  real indefinite NaN for invalid operations, as with masked exceptions.
Calls to 0x5db0d0 and 0x482f20 stay unresolved; 0x5ea2b0 is translated.
"""
import hashlib,json,re,sys
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from inspect_entrypoint import ROOT,GAME,PCRECOMP,EXPECTED,REVISION
SPECS={
 0x5daa50:[('sub','esp, 4'),('mov','ecx, dword ptr [0x7d6b48]'),('mov','edx, ecx'),('mov','dword ptr [esp], edx'),
           ('fild','dword ptr [esp]'),('mov','dword ptr [esp], ecx'),('fmul','dword ptr [0x7c8a78]'),('fdiv','dword ptr [0x7c95a0]'),
           ('fstp','dword ptr [0x7d3510]'),('fild','dword ptr [esp]'),('fild','dword ptr [0x7c8a74]'),('fsub','dword ptr [0x7c908c]'),
           ('fdivp','st(1)'),('fstp','dword ptr [0x7c8fec]'),('push','dword ptr [0x7c8fec]'),('call','0x5db0d0'),('pop','ecx'),
           ('call','0x5ea2b0'),('cmp','eax, 2'),('jne','0x5daaa8'),('call','0x482f20'),('add','esp, 4'),('ret','')],
 0x5ea2b0:[('mov','eax, dword ptr [0x7d34f8]'),('ret','')]}
SITES={0x5daa93:0x5db0d0,0x5daa99:0x5ea2b0,0x5daaa3:0x482f20}
ALLOWED={'MEM32','MEMF','PUSH32','POP32_VAL','RECOMP_ENTER','RECOMP_FLAGS_IN','RECOMP_FLAGS_OUT'}
FDIVP_GUARD='{ double _v = fp_pop(); _st[0] = _v == 0.0 ? _st[0] : _st[0] / _v; }'
FDIVP_IEEE='{ double _v = fp_pop(); _st[0] = mh_x87_div(_st[0], _v); }'
X87_OPS={'*':'mh_x87_mul','/':'mh_x87_div','-':'mh_x87_sub','+':'mh_x87_add'}
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    if (PCRECOMP/'REVISION.txt').read_text(encoding='ascii').strip()!=REVISION:raise SystemExit('unexpected tool revision')
    pe=pefile.PE(data=data,fast_load=True);decoder=Cs(CS_ARCH_X86,CS_MODE_32);extents={}
    for address,expected in SPECS.items():
        code=pe.get_data(address-pe.OPTIONAL_HEADER.ImageBase,0x60);ins=[]
        for i in decoder.disasm(code,address):
            ins.append(i)
            if len(ins)==len(expected):break
        if [(i.mnemonic,i.op_str) for i in ins]!=expected:raise SystemExit(f'unexpected instructions at {address:#x}')
        extents[address]=code[:sum(i.size for i in ins)]
    for part in ('pe','disasm','lift'):sys.path.insert(0,str(PCRECOMP/'tools'/part))
    from pe_analyze import analyze_pe,build_iat_map
    from disasm32 import Disassembler
    from lift32 import Lifter
    info=analyze_pe(str(GAME));iat=build_iat_map(info);dis=Disassembler(data,info.image_base,info.sections)
    out=ROOT/'private/analysis/candidate_time/dependencies';out.mkdir(parents=True,exist_ok=True);items=[]
    for address,expected in SPECS.items():
        func=dis.disassemble_function(address,iat)
        if not func or sum(len(b.instructions) for b in func.blocks.values())!=len(expected):raise SystemExit(f'unexpected extent at {address:#x}')
        if set(func.calls_to)!=(set(SITES.values()) if address==0x5daa50 else set()):raise SystemExit(f'unexpected calls at {address:#x}')
        source=Lifter(iat_map=iat).lift_function(func)
        if 'RECOMP_TODO' in source:raise SystemExit(f'unsupported instruction at {address:#x}')
        lifted=hashlib.sha256(source.encode()).hexdigest();header=''
        if address==0x5daa50:
            source,n=re.subn(r'\*\(float\*\)ADDR\((0x[0-9A-F]+)\)',r'MEMF(\1)',source)
            if n!=5:raise SystemExit('unexpected float access count')
            if source.count(FDIVP_GUARD)!=1:raise SystemExit('unexpected fdivp form')
            source=source.replace(FDIVP_GUARD,FDIVP_IEEE)
            source,n=re.subn(r'_st\[0\] ([*/+-])= \(double\)MEMF\((0x[0-9A-F]+)\);',lambda m:f'_st[0] = {X87_OPS[m.group(1)]}(_st[0], (double)MEMF({m.group(2)}));',source)
            if n!=3:raise SystemExit('unexpected x87 memory operation count')
            if re.search(r'_st\[\d\]\s*[*/+-]=|_st\[0\] / _v',source):raise SystemExit('x87 arithmetic left without helper')
            for site,target in SITES.items():
                pattern=rf'RECOMP_CALL\(sub_{target:08X}\); /\* 0x{site:08X}: call 0x{target:x} \*/'
                source,n=re.subn(pattern,f'MH_RECOMP_CALL_AT(sub_{target:08X}, 0x{site+5:08X}u);',source)
                if n!=1:raise SystemExit('call replacement mismatch')
            header='#include "x87_semantics.h"\nvoid sub_005DB0D0(void);\nvoid sub_005EA2B0(void);\nvoid sub_00482F20(void);\n'
        if 'ADDR(' in source:raise SystemExit(f'raw guest pointer left at {address:#x}')
        helpers=set(re.findall(r'\b(recomp_\w+)\s*\(',source))
        if helpers:raise SystemExit(f'unchecked runtime helpers at {address:#x}: '+','.join(sorted(helpers)))
        operations=set(re.findall(r'\b(?:MEM\w+|ADDR|RECOMP_\w+|PUSH\w+|POP\w+)\s*(?=\()',source))
        if not operations.issubset(ALLOWED):raise SystemExit(f'unsupported operations at {address:#x}: '+','.join(sorted(operations-ALLOWED)))
        name=f'dep_{address:08x}_precise.c';text=header+source
        (out/name).write_text(text+'\n',encoding='utf-8')
        items.append({'address':hex(address),'source':name,'instructions':len(expected),'bytes_sha256':hashlib.sha256(extents[address]).hexdigest(),
                      'bytes_length':len(extents[address]),'lifted_sha256':lifted,'adapted_sha256':hashlib.sha256(text.encode()).hexdigest(),'operations':sorted(operations)})
    (out/'x87_report.json').write_text(json.dumps({'input_sha256':EXPECTED,'items':items,
        'sites':[{'call':hex(a),'return':hex(a+5)} for a in sorted(SITES)],
        'rewrites':['5 float accesses to MEMF','fdivp zero guard removed','4 x87 operations through x87_semantics.h helpers'],
        'limitations':['x87 modelled with host double, not 80-bit extended; precision control not modelled',
                       'FPU status and exception flags not modelled','reachability unproved','not integrated into game']},indent=2)+'\n',encoding='utf-8')
    print('translated 0x5daa50 and 0x5ea2b0; sources remain private')
if __name__=='__main__':main()
