"""Lift the boot up to WinMain's first frames: boot phase 2 plus WinMain (0x4c1080).

Closure: every function with code executed in the x86 references of boot phase 2
(private/analysis/static_init/trace.json) and of WinMain up to the first presented
frames (private/analysis/winmain/trace.json, tools/trace_static_init_x86.py --winmain),
following direct calls and covering code reached indirectly (window/dialog procedures,
vtables). Game functions replaced by the port (tools/winmain_apis.py) are provided by
the runtime, never translated. x87 goes through the audited rewrites of recomp_lift.
"""
import hashlib,json,zlib
import pefile
from recomp_lift import lift_closure
from inspect_entrypoint import ROOT,GAME,EXPECTED
from lift_boot_phase2 import STARTUP,HEADER_STUB,PRUS_SLOT,executed_closure,phase2_executed
from split_winmain_unit import split
WINMAIN=0x4c1080
REPLACED={0x4becc0}   # GetDXVersion (HLE): see tools/winmain_apis.py
def data_table_roots(pe):
    """Code addresses stored in .rdata/.data (vtables, script-command and callback tables) or used as
    instruction immediates (callbacks passed as arguments) that look
    like function entries: the target of some direct call, or 16-byte aligned right after a ret,
    jmp or padding. Functions reached only through such tables (e.g. 0x4238f0 via the
    member-pointer thunk 0x616ae0) were fail-closed stops before."""
    import struct
    from capstone import Cs,CS_ARCH_X86,CS_MODE_32
    base=pe.OPTIONAL_HEADER.ImageBase
    text=[s for s in pe.sections if s.Name.rstrip(b'\0')==b'.text'][0];code=text.get_data();t0=base+text.VirtualAddress;t1=t0+len(code)
    cs=Cs(CS_ARCH_X86,CS_MODE_32);cs.skipdata=True;calls=set();after=set();immediates=set()
    for i in cs.disasm(code,t0):
        if i.mnemonic=='call' and i.op_str.startswith('0x'):calls.add(int(i.op_str,16))
        if i.mnemonic in ('ret','jmp','nop','int3') or i.op_str in ('eax, [eax]','esi, [esi]'):after.add(i.address+i.size)
        # Code addresses passed as immediates (callbacks such as 0x58cb80, pushed for 0x61d140).
        if i.mnemonic in ('push','mov') and i.op_str.split(',')[-1].strip().startswith('0x'):
            v=int(i.op_str.split(',')[-1].strip(),16)
            if t0<=v<t1:immediates.add(v)
    found={v for v in immediates if v in calls or (v in after and v%16==0)}
    for s in pe.sections:
        if s.Name.rstrip(b'\0') not in (b'.rdata',b'.data'):continue
        raw=s.get_data()
        for off in range(0,len(raw)-3,4):
            v=struct.unpack_from('<I',raw,off)[0]
            if t0<=v<t1 and (v in calls or (v in after and v%16==0)):found.add(v)
    return found

def main():
    data=GAME.read_bytes();pe=pefile.PE(data=data)
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    trace=json.loads((ROOT/'private/analysis/winmain/trace.json').read_text(encoding='utf-8'))
    if trace['input_sha256']!=EXPECTED or trace['error'] or not trace.get('frames_reached'):
        raise SystemExit('the WinMain x86 trace is missing or did not reach its frames; run tools/trace_static_init_x86.py --winmain')
    executed=phase2_executed()|{int(b,16) for b in trace['executed_blocks']}
    # plus every recorded scenario (other languages, other input scripts)
    for path in sorted((ROOT/'private/analysis/winmain/scenarios').glob('*/trace.json')):
        scenario=json.loads(path.read_text(encoding='utf-8'))
        if scenario['input_sha256']!=EXPECTED or scenario['error'] or not scenario.get('frames_reached'):
            raise SystemExit(f'scenario {path.parent.name}: trace failed or from another executable')
        executed|={int(b,16) for b in scenario['executed_blocks']}
    crt=[s for s in pe.sections if s.Name.rstrip(b'\0')==b'.CRT'][0];raw=crt.get_data()[:crt.Misc_VirtualSize]
    inits=[p for p in (int.from_bytes(raw[i:i+4],'little') for i in range(0,len(raw)//4*4,4)) if p]
    kept,stopped=executed_closure(data,[a for a,_ in STARTUP]+inits+[WINMAIN],executed,skip=REPLACED)
    print(len(kept),'executed functions;',len(stopped),'never-executed callees, translated with their static closure')
    imports={imp.address for e in pe.DIRECTORY_ENTRY_IMPORT for imp in e.imports}
    # Every function statically reachable from the executed ones is translated too (a free session
    # reaches level-script commands and branches no scenario traced yet; before, they were stops).
    # Executed functions must translate; one never executed that fails the audit (e.g. the CRT's
    # SSE2 paths) stays a fail-closed stop (auto_stop). Only executed code is compared with x86.
    extra=data_table_roots(pe)-set(kept)
    print(len(extra),'function pointers from data tables and code immediates added as optional roots')
    report=lift_closure(kept,{HEADER_STUB}|REPLACED,imports,'winmain',max_functions=40000,indirect=True,
                        auto_stop=True,x87=True,provided={HEADER_STUB}|REPLACED,dispatch_slots={PRUS_SLOT},extra_roots=extra)
    out=ROOT/'private/analysis/winmain'
    (out/'winmain_list.h').write_text('/* Generated by tools/lift_winmain.py from the user\'s executable; private. */\n'
        f'#define EXE_SIZE {len(data)}u\n#define EXE_CRC32 0x{zlib.crc32(data):08x}u\n',encoding='utf-8',newline='\n')
    x87=sum(1 for i in report['items'] if any(k in r for r in i['rewrites'] for k in ('x87','float','fsqrt','fistp')))
    print(len(report['items']),'functions,',sum(i['instructions'] for i in report['items']),'instructions;',x87,'with audited x87 rewrites;',
          len(report['imports']),'imports;',len(report['unresolved']),'fail-closed stops;',split(),'compiled parts')
if __name__=='__main__':main()
