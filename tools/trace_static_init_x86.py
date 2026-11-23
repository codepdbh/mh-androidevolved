"""Trace all 98 C++ static initialisers on x86 (Unicorn) to learn what really runs.

The protection wrapper (.prus/.izbf) is never executed: calls through its slot
[0x850000] are replaced per call site using private/analysis/protection/redirects.json
(tools/resolve_protection_redirects.py); the header stub 0x400080 is the game's own
file content and runs as is. A trigger site or any other entry into the wrapper stops.

Maps the verified executable like runtime/pe32_image.c, points every import slot
at a fake address and emulates the Windows APIs whose port semantics are
defined; any other API stops the trace and reports its name and arguments.
Records executed basic blocks, indirect-call targets and API calls.
Output: private/analysis/static_init/trace.json. Nothing is executed natively.
"""
import hashlib,json,os,struct,sys,zlib
from collections import Counter
import pefile
from unicorn import Uc,UcError,UC_ARCH_X86,UC_MODE_32,UC_HOOK_INSN,UC_HOOK_MEM_INVALID,UC_HOOK_CODE,UC_HOOK_BLOCK
from unicorn.x86_const import (UC_X86_REG_EAX,UC_X86_REG_EBX,UC_X86_REG_ECX,UC_X86_REG_EDX,UC_X86_REG_ESI,
    UC_X86_REG_EDI,UC_X86_REG_EBP,UC_X86_REG_ESP,UC_X86_REG_EIP,UC_X86_REG_EFLAGS,UC_X86_REG_FPCW,UC_X86_INS_CPUID)
from inspect_entrypoint import ROOT,GAME,EXPECTED
from probe_static_init_x86 import virtual_cpuid
GUEST_END,STACK_TOP,RETURN_SENTINEL,API_BASE=0x6200000,0x1800000,0x1f00000,0x1e00000
PROCESS_DATA,COMMAND_LINE=0x1f10000,b'"manhunt.exe"\0'   # process strings, outside image and heaps
GLOBAL_BASE,GLOBAL_SIZE,CS,THREAD=0x2000000,0x4100000,0x828120,0x1234
class Callbacks:
    """Returned by an API handler: call `calls` [(guest function, [args])] in order, then
    complete the API with finish(list of their eax results)."""
    def __init__(self,calls,finish):self.calls,self.finish=calls,finish
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    pe=pefile.PE(data=data);opt=pe.OPTIONAL_HEADER
    imports=[(imp.address,(imp.name.decode() if imp.name else f'ordinal_{imp.ordinal}'),e.dll.decode().lower()) for e in pe.DIRECTORY_ENTRY_IMPORT for imp in e.imports]
    crt=[s for s in pe.sections if s.Name.rstrip(b'\0')==b'.CRT'][0];raw=crt.get_data()[:crt.Misc_VirtualSize]
    inits=[p for p in struct.unpack('<%dI'%(len(raw)//4),raw[:len(raw)//4*4]) if p]
    cpu=Uc(UC_ARCH_X86,UC_MODE_32);cpu.mem_map(0x400000,GUEST_END-0x400000)
    image=bytearray(opt.SizeOfImage);image[:opt.SizeOfHeaders]=data[:opt.SizeOfHeaders]
    for s in pe.sections:
        if s.SizeOfRawData:image[s.VirtualAddress:s.VirtualAddress+s.SizeOfRawData]=data[s.PointerToRawData:s.PointerToRawData+s.SizeOfRawData]
    cpu.mem_write(opt.ImageBase,bytes(image))
    w32=lambda a,v:cpu.mem_write(a,struct.pack('<I',v&0xffffffff))
    r32=lambda a:struct.unpack('<I',cpu.mem_read(a,4))[0]
    def cstr(a,limit=260):
        out=b''
        while a and len(out)<limit:
            c=bytes(cpu.mem_read(a+len(out),1))
            if c==b'\0':break
            out+=c
        return out.decode('latin-1')
    # Fake import addresses: the boot-phase-2 APIs first, in the order tests/boot_phase2_native.c uses
    # (the header stub leaves the resolved address on the stack), then every other import.
    from lift_boot_phase2 import APIS
    imports.sort(key=lambda x:(APIS.index(x[1]) if x[1] in APIS else len(APIS)))
    fake={}
    for i,(slot,name,dll) in enumerate(imports):
        address=API_BASE+0x10*(i+1);fake[address]=(name,dll,slot);w32(slot,address);cpu.mem_write(address,b'\xc3')
    ENVIRONMENT=PROCESS_DATA+0x100
    cpu.mem_write(PROCESS_DATA,COMMAND_LINE);cpu.mem_write(ENVIRONMENT,bytes(2))
    for i in range(0,24,4):w32(CS+i,0)
    w32(CS+4,0xffffffff)
    state={'next':GLOBAL_BASE,'tls':{},'events':0,'calls':[],'counts':Counter(),'last_error':0,'redirects':Counter()}
    redirects=json.loads((ROOT/'private/analysis/protection/redirects.json').read_text(encoding='utf-8'))
    if redirects['input_sha256']!=EXPECTED:raise SystemExit('stale protection redirects')
    sites={int(x['return'],16):('integrity' if x['kind']=='bounded' else x['kind']) for x in redirects['slot_sites']}
    site_values={int(x['return'],16):int(x.get('value','0'),16) for x in redirects['slot_sites']}
    site_args={int(x['return'],16):x.get('args',0) for x in redirects['slot_sites']}
    prus_target=r32(0x850000)
    ARGS={'InitializeCriticalSection':1,'EnterCriticalSection':1,'LeaveCriticalSection':1,'DeleteCriticalSection':1,'GlobalAlloc':2,'GlobalFree':1,
          'TlsGetValue':1,'TlsSetValue':2,'TlsAlloc':0,'TlsFree':1,'GetStdHandle':1,'GetCurrentProcess':0,'DuplicateHandle':7,'GetCommandLineA':0,'GetEnvironmentStrings':0,'FreeEnvironmentStringsA':1,'CreateEventA':4,'GetTickCount':0}
    extra={}   # filled for the WinMain stage (tools/winmain_apis.py)
    calllog=None   # WinMain stage: every API/COM call in order (name, return address)
    dump_at=int(os.environ.get('MH_DUMP_AT','0'))
    def logcall(text):   # MH_DUMP_AT=n: write .data/.bss at the n-th call and stop (bisecting a divergence)
        calllog.append(text)
        if dump_at and len(calllog)==dump_at:
            open(os.environ['MH_DUMP'],'wb').write(bytes(cpu.mem_read(0x67d000,0x8296d4-0x67d000)));raise SystemExit('dumped at call %d'%dump_at)
    def api(uc,address,size,user):
        if address not in fake:return
        name,dll,slot=fake[address];esp=cpu.reg_read(UC_X86_REG_ESP);ret=r32(esp)
        args=[r32(esp+4+4*i) for i in range(12)];state['counts'][name]+=1
        if calllog is not None:logcall(f'{name} {ret:x}')
        result=None
        if name in ('EnterCriticalSection','LeaveCriticalSection'):
            cs=args[0];lock,rec,owner=r32(cs+4),r32(cs+8),r32(cs+12)
            if name=='EnterCriticalSection':w32(cs+4,lock+1);w32(cs+8,rec+1);w32(cs+12,THREAD)
            else:w32(cs+4,lock-1);w32(cs+8,rec-1);w32(cs+12,0 if rec==1 else THREAD)
        elif name=='DeleteCriticalSection':pass
        elif name=='InitializeCriticalSection':
            for i in range(0,24,4):w32(args[0]+i,0)
            w32(args[0]+4,0xffffffff)
        elif name=='GlobalAlloc':
            start=(state['next']+7)&~7;n=args[1] or 1;result=0
            if not args[0]&~0x40 and start+n<=GLOBAL_BASE+GLOBAL_SIZE:cpu.mem_write(start,bytes(n));state['next']=start+n;result=start
        elif name=='GlobalFree':result=0
        elif name=='TlsGetValue':
            if args[0] in state['tls']:result=state['tls'][args[0]];state['last_error']=0
            else:result=0;state['last_error']=87
        elif name=='TlsSetValue':
            if args[0] in state['tls']:state['tls'][args[0]]=args[1];result=1
            else:result=0;state['last_error']=87
        elif name=='GetStdHandle':result=0   # GUI process without a console: no standard handles
        elif name=='GetCurrentProcess':result=0xffffffff   # pseudo-handle
        elif name=='DuplicateHandle' and args[1]==0:result=0;state['last_error']=6   # NULL source: ERROR_INVALID_HANDLE
        elif name=='GetCommandLineA':result=PROCESS_DATA
        elif name=='GetEnvironmentStrings':result=ENVIRONMENT   # empty block: two NULs
        elif name=='FreeEnvironmentStringsA':result=int(args[0]==ENVIRONMENT)
        elif name=='TlsAlloc':   # lowest free index, as runtime/win32_thread.c
            result=next((i for i in range(64) if i not in state['tls']),0xffffffff)
            if result!=0xffffffff:state['tls'][result]=0
        elif name=='TlsFree':
            result=int(args[0] in state['tls'])
            if result:del state['tls'][args[0]]
            else:state['last_error']=87
        elif name=='CreateEventA':state['events']+=1;result=0x50000000|state['events']
        elif name=='GetTickCount':result=0x10000
        elif name in extra:result=extra[name][1](args)
        else:
            state['calls'].append({'api':name,'dll':dll,'args':[hex(a) for a in args[:6]],'return':hex(ret),
                                   'strings':[cstr(a) for a in args[:4] if 0x400000<=a<GUEST_END]})
            raise SystemExit(f'unsupported API {dll}!{name} called from {ret:#x} with {[hex(a) for a in args[:6]]}: {state["calls"][-1]["strings"]}')
        pop=esp+4+4*(ARGS[name] if name in ARGS else extra[name][0])
        if isinstance(result,Callbacks):   # the API calls back into the game before it returns
            pending.append({'calls':list(result.calls),'finish':result.finish,'results':[],'esp':esp,'pop':pop,'ret':ret})
            next_callback();return
        if result is not None:cpu.reg_write(UC_X86_REG_EAX,result)
        cpu.reg_write(UC_X86_REG_ESP,pop);cpu.reg_write(UC_X86_REG_EIP,ret)
    # Synchronous callbacks (window procedures called from inside an API, as Windows does):
    # each is a stdcall into guest code that returns to CONTINUE, where the next one starts or
    # the API completes with finish(results).
    CONTINUE=API_BASE+0x10*(len(imports)+3);cpu.mem_write(CONTINUE,b'\xc3');pending=[]
    def next_callback():
        frame=pending[-1]
        if frame['calls']:
            fn,cargs=frame['calls'].pop(0);sp=frame['esp']-0x40-4*len(cargs)
            w32(sp,CONTINUE)
            for i,v in enumerate(cargs):w32(sp+4+4*i,v)
            cpu.reg_write(UC_X86_REG_ESP,sp);cpu.reg_write(UC_X86_REG_EIP,fn);frame['sp']=sp;frame['argc']=len(cargs)
            return
        result=frame['finish'](frame['results'])
        if isinstance(result,Callbacks):   # the API decided to call back again (e.g. a dialog's next message)
            frame['calls'],frame['finish'],frame['results']=list(result.calls),result.finish,[];next_callback();return
        pending.pop()
        if result is not None:cpu.reg_write(UC_X86_REG_EAX,result)
        cpu.reg_write(UC_X86_REG_ESP,frame['pop']);cpu.reg_write(UC_X86_REG_EIP,frame['ret'])
    def continued(uc,address,size,user):
        frame=pending[-1]
        if cpu.reg_read(UC_X86_REG_ESP)!=frame['sp']+4+4*frame['argc']:raise SystemExit('callback did not pop its arguments (not stdcall)')
        frame['results'].append(cpu.reg_read(UC_X86_REG_EAX));next_callback()
    cpu.hook_add(UC_HOOK_CODE,continued,begin=CONTINUE,end=CONTINUE)
    # COM methods of the port's shims (tools/winmain_apis.py): fake addresses COM_VA + 0x100*interface
    # + 4*method, stdcall with `this` first; the handler returns eax or Callbacks.
    COM_VA=0x1e10000
    def com(uc,address,size,user):
        if 'com' not in extra:return
        esp=cpu.reg_read(UC_X86_REG_ESP);ret=r32(esp)
        nargs,result,label=extra['com'][1](address,lambda i:r32(esp+4+4*i))
        state['counts'][label]+=1;pop=esp+4+4*nargs
        if calllog is not None:logcall(f'{label} {ret:x}')
        if isinstance(result,Callbacks):
            pending.append({'calls':list(result.calls),'finish':result.finish,'results':[],'esp':esp,'pop':pop,'ret':ret});next_callback();return
        if result is not None:cpu.reg_write(UC_X86_REG_EAX,result)
        cpu.reg_write(UC_X86_REG_ESP,pop);cpu.reg_write(UC_X86_REG_EIP,ret)
    cpu.hook_add(UC_HOOK_CODE,com,begin=COM_VA,end=COM_VA+0x10000)
    # Game functions replaced by the port (HLE), from tools/winmain_apis.py: cdecl, address -> eax.
    def replaced(uc,address,size,user):
        table=extra.get('replaced',(0,{}))[1]
        if address not in table:return
        esp=cpu.reg_read(UC_X86_REG_ESP);name,fn=table[address];state['counts'][name]+=1
        if calllog is not None:logcall(f'{name} {r32(esp):x}')
        cpu.reg_write(UC_X86_REG_EAX,fn());cpu.reg_write(UC_X86_REG_ESP,esp+4);cpu.reg_write(UC_X86_REG_EIP,r32(esp))
    cpu.hook_add(UC_HOOK_CODE,api,begin=API_BASE,end=API_BASE+0x10*(len(imports)+2))
    cpu.hook_add(UC_HOOK_INSN,virtual_cpuid,None,1,0,UC_X86_INS_CPUID)
    # rdtsc: the port's deterministic counter (runtime/port_api.c mh_port_rdtsc): virtual clock x 1e6 + reads.
    # (Unicorn's Python binding has no instruction hook for rdtsc: a code hook on every 0F 31 in
    # the code sections sets edx:eax and skips the two bytes; at other offsets it never fires.)
    tsc={'reads':0};RDTSC=bytes((0x0f,0x31))
    def virtual_rdtsc(uc,address,size,user):
        if bytes(uc.mem_read(address,2))!=RDTSC:return
        tsc['reads']+=1;v=state.get('clock',0x10000)*1000000+tsc['reads']
        uc.reg_write(UC_X86_REG_EAX,v&0xffffffff);uc.reg_write(UC_X86_REG_EDX,(v>>32)&0xffffffff);uc.reg_write(UC_X86_REG_EIP,address+2)
    # fyl2x / fyl2xp1 outside their domain: Unicorn (old QEMU) leaves the stack unchanged and sets C2,
    # where an x87 produces a result and pops: NaN operands propagate, a negative argument (x < 0,
    # or x <= -1 for fyl2xp1) gives the indefinite NaN, and log2(0) gives -inf times y (indefinite
    # when y is 0); the port follows the hardware (recomp/x87_semantics.h). The hook sets ST0 = 2.0 and
    # ST1 = that result, so the instruction itself computes log2(2) * result and pops.
    import math
    from unicorn.x86_const import UC_X86_REG_FPSW,UC_X86_REG_FP0
    def f80_read(i):
        top=(cpu.reg_read(UC_X86_REG_FPSW)>>11)&7;mant,exp=cpu.reg_read(UC_X86_REG_FP0+((top+i)&7))
        sign=-1.0 if exp&0x8000 else 1.0;e=exp&0x7fff
        if e==0x7fff:return float('nan') if mant&0x7fffffffffffffff else sign*math.inf
        return sign*math.ldexp(mant,e-16383-63) if mant else sign*0.0
    def f80_write(i,v):
        top=(cpu.reg_read(UC_X86_REG_FPSW)>>11)&7
        if v!=v:raw=(0xC000000000000000,0xFFFF)   # the x87 indefinite (negative quiet NaN)
        elif math.isinf(v):raw=(0x8000000000000000,0xFFFF if v<0 else 0x7FFF)
        elif v==0:raw=(0,0x8000 if math.copysign(1,v)<0 else 0)
        else:
            m,e=math.frexp(abs(v));raw=(int(m*(1<<64))&0xffffffffffffffff,(e-1+16383)|(0x8000 if v<0 else 0))
        cpu.reg_write(UC_X86_REG_FP0+((top+i)&7),raw)
    LOG_OPS={bytes((0xd9,0xf1)):0,bytes((0xd9,0xf9)):1}
    def x87_log_domain(uc,address,size,user):
        op=LOG_OPS.get(bytes(uc.mem_read(address,2)))
        if op is None:return
        x,y=f80_read(0),f80_read(1)
        if x!=x or y!=y:r=float('nan')
        elif (op==0 and x<0) or (op==1 and x<=-1):r=float('nan')
        elif op==0 and x==0:r=float('nan') if y==0 else (-math.inf if y>0 else math.inf)
        else:return   # in the domain: Unicorn computes it
        f80_write(1,r);f80_write(0,2.0)
    # fnstsw: Unicorn keeps C1 (FPSW bit 9) from earlier arithmetic (rounding up) through comparisons,
    # where an x87 clears it (FCOM/FTST/FLD set C1 = 0 without a stack fault). The port's status word
    # carries only the compare's C0/C2/C3 (C1 = 0), so the hook clears C1 before each fnstsw: the
    # game masks it away, but `fnstsw ax` leaves it in eax (pushed later, e.g. as stack residue).
    from unicorn.x86_const import UC_X86_REG_FPSW as _FPSW
    def clear_c1(uc,address,size,user):uc.reg_write(_FPSW,uc.reg_read(_FPSW)&~0x200)
    for lo,hi in ((0x401000,0x66e200),(0x66f000,0x66f451)):
        code=bytes(cpu.mem_read(lo,hi-lo));at=code.find(bytes((0xdf,0xe0)))   # fnstsw ax
        while at>=0:cpu.hook_add(UC_HOOK_CODE,clear_c1,begin=lo+at,end=lo+at);at=code.find(bytes((0xdf,0xe0)),at+1)
        for at in range(len(code)-1):   # fnstsw m16: dd /7 with a memory operand
            if code[at]==0xdd and (code[at+1]>>3)&7==7 and code[at+1]>>6!=3:cpu.hook_add(UC_HOOK_CODE,clear_c1,begin=lo+at,end=lo+at)
    for lo,hi in ((0x401000,0x66e200),(0x66f000,0x66f451)):
        code=bytes(cpu.mem_read(lo,hi-lo))
        for pat in LOG_OPS:
            at=code.find(pat)
            while at>=0:cpu.hook_add(UC_HOOK_CODE,x87_log_domain,begin=lo+at,end=lo+at);at=code.find(pat,at+1)
    for lo,hi in ((0x401000,0x66e200),(0x66f000,0x66f451)):
        code=bytes(cpu.mem_read(lo,hi-lo));at=code.find(RDTSC)
        while at>=0:cpu.hook_add(UC_HOOK_CODE,virtual_rdtsc,begin=lo+at,end=lo+at);at=code.find(RDTSC,at+1)
    # Unicorn starts with FPCW=0 (24-bit precision, exceptions unmasked); a Windows process starts
    # with 0x027F (53-bit precision, all exceptions masked), which the port models.
    cpu.reg_write(UC_X86_REG_FPCW,0x027f)
    from collections import deque
    blocks=set();recent=deque(maxlen=12)
    def on_block(uc,address,size,user):   # one Python call per block: executed .text blocks and the last 12 blocks
        recent.append(address)
        if 0x401000<=address<0x66e200 or 0x66f000<=address<0x66f451:blocks.add(address)   # .text and _rwcseg (RenderWare x87 code)
    cpu.hook_add(UC_HOOK_BLOCK,on_block)
    if os.environ.get('MH_WATCH'):   # debugging: report every write to one guest address (writer EIP, value, recent blocks)
        from unicorn import UC_HOOK_MEM_WRITE
        watch=int(os.environ['MH_WATCH'],16)
        def watched(uc,access,address,size,value,user):
            print('WRITE %#x size %d value %#x eip %#x calls %d recent %s'%(address,size,value&0xffffffff,uc.reg_read(UC_X86_REG_EIP),
                  len(calllog) if calllog is not None else -1,' '.join(hex(b) for b in recent)),flush=True)
        cpu.hook_add(UC_HOOK_MEM_WRITE,watched,begin=watch,end=watch+3)
    # The wrapper's own code is never executed (it is filled at run time). Calls through
    # its slot are replaced by what each call site needs, as in runtime/protection_redirect.c.
    def protected(uc,address,size,user):
        esp=cpu.reg_read(UC_X86_REG_ESP);ret=r32(esp);kind=sites.get(ret)
        if address!=prus_target or kind is None:raise SystemExit(f'execution entered the protection wrapper at {address:#x} from {ret:#x}')
        if kind=='get_last_error':cpu.reg_write(UC_X86_REG_EAX,state['last_error']);pop=4
        elif kind=='validate_pointer':
            pointer,size_=r32(esp+4),r32(esp+8)
            try:bad=0 if not size_ else (cpu.mem_read(pointer,size_) is None)
            except UcError:bad=1
            cpu.reg_write(UC_X86_REG_EAX,int(bad));pop=12
        elif kind=='integrity':cpu.reg_write(UC_X86_REG_EAX,site_values[ret]);pop=4+4*site_args[ret]   # the answer of an intact copy (as runtime/game_runner.c)
        elif kind=='mirror':
            h=site_args[ret]&0x7f
            if site_args[ret]&0x80:w32(r32(esp+4+4*h+4),site_values[ret])
            cpu.reg_write(UC_X86_REG_EAX,site_values[ret]);pop=4+4*h
        elif kind=='store':
            ecx=cpu.reg_read(UC_X86_REG_ECX);w32(cpu.reg_read(UC_X86_REG_EBX),ecx);cpu.reg_write(UC_X86_REG_EAX,ecx);pop=4
        elif kind=='resume':   # the intact wrapper drops its arguments and continues at esi's label
            state['redirects'][kind]+=1;cpu.reg_write(UC_X86_REG_ESP,esp+4+4*site_args[ret]);cpu.reg_write(UC_X86_REG_EIP,site_values[ret]);return
        else:raise SystemExit(f'protection trigger site returning to {ret:#x} reached; not handled yet')
        state['redirects'][kind]+=1
        cpu.reg_write(UC_X86_REG_ESP,esp+pop);cpu.reg_write(UC_X86_REG_EIP,ret)
    cpu.hook_add(UC_HOOK_CODE,protected,begin=0x850000,end=0xa16000)
    faults=[];cpu.hook_add(UC_HOOK_MEM_INVALID,lambda uc,access,addr,size,value,user:faults.append((addr,uc.reg_read(UC_X86_REG_EIP))) or False)
    done=[];error=None;results=[]
    # The CRT entry 0x64a380 (reached only from the wrapper) calls 0x653460(0x7eba68) and the
    # CRT initialisation 0x655490 (TLS, locks) before walking .CRT; run them first, in that order.
    startup=[(0x653460,(0x7eba68,)),(0x655490,())]
    for address,cargs in startup+[(a,()) for a in inits]:
        for reg,value in ((UC_X86_REG_EAX,0x11111111),(UC_X86_REG_EBX,0x22222222),(UC_X86_REG_ECX,0x33333333),(UC_X86_REG_EDX,0x44444444),
                          (UC_X86_REG_ESI,0x55555555),(UC_X86_REG_EDI,0x66666666),(UC_X86_REG_EBP,0x77777777),(UC_X86_REG_ESP,STACK_TOP),(UC_X86_REG_EFLAGS,0x202)):
            cpu.reg_write(reg,value)
        w32(STACK_TOP,RETURN_SENTINEL)
        for i,a in enumerate(cargs):w32(STACK_TOP+4+4*i,a)
        try:cpu.emu_start(address,RETURN_SENTINEL,timeout=120000000,count=200000000)
        except UcError as exc:
            error=f'initialiser {address:#x} faulted: {exc}'+(f' at {faults[-1][0]:#x} (eip {faults[-1][1]:#x})' if faults else '')+' recent blocks '+' '.join(hex(x) for x in recent);break
        except SystemExit as exc:error=f'initialiser {address:#x}: {exc}';break
        if cpu.reg_read(UC_X86_REG_EIP)!=RETURN_SENTINEL:error=f'initialiser {address:#x} did not return';break
        if cpu.reg_read(UC_X86_REG_ESP)!=STACK_TOP+4:error=f'initialiser {address:#x} left esp {cpu.reg_read(UC_X86_REG_ESP):#x}';break
        done.append(hex(address))
        results.append([address]+[cpu.reg_read(r) for r in (UC_X86_REG_EAX,UC_X86_REG_EBX,UC_X86_REG_ECX,UC_X86_REG_EDX,UC_X86_REG_ESI,UC_X86_REG_EDI)])
    out=ROOT/'private/analysis/static_init';out.mkdir(parents=True,exist_ok=True)
    (out/'trace.json').write_text(json.dumps({'input_sha256':EXPECTED,'completed':done,'error':error,'api_counts':dict(state['counts']),'redirects':dict(state['redirects']),
        'unsupported_calls':state['calls'],'executed_blocks':sorted(hex(b) for b in blocks)},indent=1)+'\n',encoding='utf-8')
    # x86 reference for tests/boot_phase2_native.c, once the whole boot completes and the unit exists.
    report_path=ROOT/'private/analysis/boot_phase2/boot_phase2_report.json'
    if not error and report_path.exists():
        from lift_boot_phase2 import APIS
        read=lambda a,n:bytes(cpu.mem_read(a,n))
        case={'image':[opt.ImageBase,opt.SizeOfImage,opt.AddressOfEntryPoint],'results':results,
              'api_calls':[state['counts'].get(n,0) for n in APIS],
              'redirects':[state['redirects'].get('get_last_error',0),state['redirects'].get('validate_pointer',0)],
              'last_error':state['last_error'],'tls':sorted([i,v] for i,v in state['tls'].items()),'events':state['events'],'global_next':state['next'],
              'data_crc':zlib.crc32(read(0x67d000,0x7ed4a0-0x67d000)),'bss_crc':zlib.crc32(read(0x81e000,0x8296d4-0x81e000)),
              'image_crc':[zlib.crc32(read(0x400000,0x81b000-0x400000)),zlib.crc32(read(0x81c2a0,0xa16000-0x81c2a0))],  # without the two import tables
              'stack_crc':zlib.crc32(read(STACK_TOP-0x4000,0x4004)),
              'global_crc':zlib.crc32(read(GLOBAL_BASE,state['next']-GLOBAL_BASE)),'fpu_cw':cpu.reg_read(UC_X86_REG_FPCW)}
        unit=json.loads(report_path.read_text(encoding='utf-8'))['unit_sha256']
        (ROOT/'private/analysis/boot_phase2/x86_reference.json').write_text(json.dumps({'input_sha256':EXPECTED,'unit_sha256':unit,'cases':[case]},indent=2)+'\n',encoding='utf-8')
        print('boot phase 2 x86 reference written')
    print(len(done),'of',len(startup)+len(inits),'startup steps and initialisers completed;',len(blocks),'executed blocks; APIs',dict(state['counts']),'; redirects',dict(state['redirects']))
    if error:print('STOP:',error)
    if error or '--winmain' not in sys.argv:return
    # WinMain stage: as the CRT entry does after .CRT, call WinMain(GetModuleHandleA(0), 0,
    # command line past the program name ([0x82926c] = offset set by the CRT), nShowCmd).
    # GetStartupInfoA gives no STARTF_USESHOWWINDOW, so nShowCmd is SW_SHOWDEFAULT (10).
    import winmain_apis
    extra.update(winmain_apis.make({'cpu':cpu,'r32':r32,'w32':w32,'cstr':cstr,'state':state,'Callbacks':Callbacks,'game_dir':str(GAME.parent),'frames':int(sys.argv[sys.argv.index('--frames')+1]) if '--frames' in sys.argv else 3}))
    for address in extra.get('replaced',(0,{}))[1]:cpu.hook_add(UC_HOOK_CODE,replaced,begin=address,end=address)
    phase2_blocks=set(blocks);state['counts'].clear();calllog=[]
    for reg,value in ((UC_X86_REG_EAX,0x11111111),(UC_X86_REG_EBX,0x22222222),(UC_X86_REG_ECX,0x33333333),(UC_X86_REG_EDX,0x44444444),
                      (UC_X86_REG_ESI,0x55555555),(UC_X86_REG_EDI,0x66666666),(UC_X86_REG_EBP,0x77777777),(UC_X86_REG_ESP,STACK_TOP),(UC_X86_REG_EFLAGS,0x202)):
        cpu.reg_write(reg,value)
    cmdline=PROCESS_DATA+r32(0x82926c)
    for i,v in enumerate((RETURN_SENTINEL,opt.ImageBase,0,cmdline,10)):w32(STACK_TOP+4*i,v)
    werror=None;reached=None
    try:cpu.emu_start(0x4c1080,RETURN_SENTINEL,timeout=0,count=0)
    except UcError as exc:werror=f'faulted: {exc}'+(f' at {faults[-1][0]:#x} (eip {faults[-1][1]:#x})' if faults else '')+' recent blocks '+' '.join(hex(x) for x in recent)
    except SystemExit as exc:werror=str(exc)
    except extra['FramesReached'][1] as exc:werror=None;reached=str(exc)
    new_blocks=blocks-phase2_blocks
    out=ROOT/'private/analysis/winmain'
    # Further scenarios (MH_SCENARIO=name: another language or input script) are written to
    # winmain/scenarios/<name>/; tools/lift_winmain.py translates the union of all their code and
    # scripts/worksafe.py test_winmain compares each one.
    if os.environ.get('MH_SCENARIO'):
        import re as _re
        if not _re.fullmatch(r'[a-z0-9_]{1,32}',os.environ['MH_SCENARIO']):raise SystemExit('invalid scenario name')
        out=out/'scenarios'/os.environ['MH_SCENARIO']
    out.mkdir(parents=True,exist_ok=True)
    (out/'trace.json').write_text(json.dumps({'input_sha256':EXPECTED,'error':werror,'returned':werror is None and reached is None,'frames_reached':reached,'eax':cpu.reg_read(UC_X86_REG_EAX),
        'api_counts':dict(state['counts']),'unsupported_calls':state['calls'],'executed_blocks':sorted(hex(b) for b in new_blocks)},indent=1)+'\n',encoding='utf-8')
    (out/'calls.txt').write_text('\n'.join(calllog)+'\n',encoding='utf-8')
    # Import table in this reference's fake-address order (tests/winmain_native.c assigns the same).
    (out/'winmain_imports.h').write_text('/* Generated by tools/trace_static_init_x86.py; private. Import slots in fake-address order. */\n'
        f'#define WINMAIN_IMPORTS {len(imports)}u\nstatic const struct {{ uint32_t slot; const char *name; }} winmain_imports[WINMAIN_IMPORTS]={{\n'
        +''.join(f'    {{0x{slot:x}u,"{name}"}},\n' for slot,name,dll in imports)+'};\n',encoding='utf-8',newline='\n')
    if reached:
        read=lambda a,n:bytes(cpu.mem_read(a,n))
        com=state['com'];res_next=state.get('res_next',0x10000000)
        case={'calls':len(calllog),'api_counts':dict(sorted(state['counts'].items())),'clock':state['clock'],'frames':state.get('frames',0),
              'last_error':state['last_error'],'global_next':state['next'],'com_next':com['next'],'res_next':res_next,
              'data_crc':zlib.crc32(read(0x67d000,0x7ed4a0-0x67d000)),'bss_crc':zlib.crc32(read(0x81e000,0x8296d4-0x81e000)),
              'image_crc':[zlib.crc32(read(0x400000,0x81b000-0x400000)),zlib.crc32(read(0x81c2a0,0xa16000-0x81c2a0))],
              'stack_crc':zlib.crc32(read(STACK_TOP-0x10000,0x10014)),'global_crc':zlib.crc32(read(GLOBAL_BASE,state['next']-GLOBAL_BASE)),
              'com_crc':zlib.crc32(read(0x1e40000,com['next']-0x1e40000)),'res_crc':zlib.crc32(read(0x10000000,res_next-0x10000000)),
              'fpu_cw':cpu.reg_read(UC_X86_REG_FPCW)}
        report=ROOT/'private/analysis/winmain/winmain_report.json'
        unit=json.loads(report.read_text(encoding='utf-8'))['unit_sha256'] if report.exists() else None
        if os.environ.get('MH_DUMP'):open(os.environ['MH_DUMP'],'wb').write(read(0x67d000,0x8296d4-0x67d000))
        if os.environ.get('MH_DUMP_STACK'):open(os.environ['MH_DUMP_STACK'],'wb').write(read(STACK_TOP-0x10000,0x10014))   # the stack_crc range
        if os.environ.get('MH_DUMP_GLOBAL'):open(os.environ['MH_DUMP_GLOBAL'],'wb').write(read(GLOBAL_BASE,state['next']-GLOBAL_BASE))
        (out/'x86_reference.json').write_text(json.dumps({'input_sha256':EXPECTED,'unit_sha256':unit,'keys':os.environ.get('MH_KEYS',''),'lang':os.environ.get('MH_LANG','0409'),'cases':[case]},indent=1)+'\n',encoding='utf-8')
        print('WinMain x86 reference written: res memory',hex(res_next-0x10000000),'COM heap',hex(com['next']-0x1e40000),'calls',len(calllog))
    print('WinMain:',len(new_blocks),'new blocks; APIs',dict(state['counts']))
    print('WinMain STOP:',werror) if werror else print('WinMain: stopped after',reached) if reached else print('WinMain returned',hex(cpu.reg_read(UC_X86_REG_EAX)))
if __name__=='__main__':main()
