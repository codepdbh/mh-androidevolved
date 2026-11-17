"""Trace all 98 C++ static initialisers on x86 (Unicorn) to learn what really runs.

Stops, by policy, if execution enters the protection wrapper sections (.prus/.izbf).

Maps the verified executable like runtime/pe32_image.c, points every import slot
at a fake address and emulates the Windows APIs whose port semantics are
defined; any other API stops the trace and reports its name and arguments.
Records executed basic blocks, indirect-call targets and API calls.
Output: private/analysis/static_init/trace.json. Nothing is executed natively.
"""
import hashlib,json,struct,sys
from collections import Counter
import pefile
from unicorn import Uc,UcError,UC_ARCH_X86,UC_MODE_32,UC_HOOK_INSN,UC_HOOK_MEM_INVALID,UC_HOOK_CODE,UC_HOOK_BLOCK
from unicorn.x86_const import (UC_X86_REG_EAX,UC_X86_REG_EBX,UC_X86_REG_ECX,UC_X86_REG_EDX,UC_X86_REG_ESI,
    UC_X86_REG_EDI,UC_X86_REG_EBP,UC_X86_REG_ESP,UC_X86_REG_EIP,UC_X86_REG_EFLAGS,UC_X86_INS_CPUID)
from inspect_entrypoint import ROOT,GAME,EXPECTED
from probe_static_init_x86 import virtual_cpuid
GUEST_END,STACK_TOP,RETURN_SENTINEL,API_BASE=0x6200000,0x1800000,0x1f00000,0x1e00000
GLOBAL_BASE,GLOBAL_SIZE,CS,THREAD=0x2000000,0x4100000,0x828120,0x1234
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
    fake={}
    for i,(slot,name,dll) in enumerate(imports):
        address=API_BASE+0x10*(i+1);fake[address]=(name,dll,slot);w32(slot,address);cpu.mem_write(address,b'\xc3')
    for i in range(0,24,4):w32(CS+i,0)
    w32(CS+4,0xffffffff)
    state={'next':GLOBAL_BASE,'tls':{},'events':0,'calls':[],'counts':Counter()}
    ARGS={'InitializeCriticalSection':1,'EnterCriticalSection':1,'LeaveCriticalSection':1,'DeleteCriticalSection':1,'GlobalAlloc':2,'GlobalFree':1,
          'TlsGetValue':1,'TlsSetValue':2,'CreateEventA':4,'GetTickCount':0}
    def api(uc,address,size,user):
        if address not in fake:return
        name,dll,slot=fake[address];esp=cpu.reg_read(UC_X86_REG_ESP);ret=r32(esp)
        args=[r32(esp+4+4*i) for i in range(8)];state['counts'][name]+=1
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
        elif name=='TlsGetValue':result=state['tls'].get(args[0],0)
        elif name=='TlsSetValue':state['tls'][args[0]]=args[1];result=1
        elif name=='CreateEventA':state['events']+=1;result=0x50000000|state['events']
        elif name=='GetTickCount':result=0x10000
        else:
            state['calls'].append({'api':name,'dll':dll,'args':[hex(a) for a in args[:6]],'return':hex(ret),
                                   'strings':[cstr(a) for a in args[:4] if 0x400000<=a<GUEST_END]})
            raise SystemExit(f'unsupported API {dll}!{name} called from {ret:#x} with {[hex(a) for a in args[:6]]}: {state["calls"][-1]["strings"]}')
        if name in ('GlobalAlloc','GlobalFree','TlsGetValue','TlsSetValue','CreateEventA','GetTickCount'):cpu.reg_write(UC_X86_REG_EAX,result)
        cpu.reg_write(UC_X86_REG_ESP,esp+4+4*ARGS[name]);cpu.reg_write(UC_X86_REG_EIP,ret)
    cpu.hook_add(UC_HOOK_CODE,api,begin=API_BASE,end=API_BASE+0x10*(len(imports)+2))
    cpu.hook_add(UC_HOOK_INSN,virtual_cpuid,None,1,0,UC_X86_INS_CPUID)
    blocks=set();cpu.hook_add(UC_HOOK_BLOCK,lambda uc,address,size,user:blocks.add(address),begin=0x401000,end=0x66e200)
    recent=[];cpu.hook_add(UC_HOOK_BLOCK,lambda uc,address,size,user:(recent.append(address),recent.pop(0) if len(recent)>12 else None))
    # Policy (AGENTS.md: no circumvention of protections): .prus/.izbf belong to the
    # executable's protection wrapper and are filled at run time. The port never
    # executes, emulates or reconstructs that code; reaching it stops the trace.
    def protected(uc,address,size,user):raise SystemExit(f'execution reached the protection wrapper at {address:#x}; stopped by policy')
    cpu.hook_add(UC_HOOK_CODE,protected,begin=0x850000,end=0xa16000)
    faults=[];cpu.hook_add(UC_HOOK_MEM_INVALID,lambda uc,access,addr,size,value,user:faults.append((addr,uc.reg_read(UC_X86_REG_EIP))) or False)
    done=[];error=None
    for address in inits:
        for reg,value in ((UC_X86_REG_EAX,0x11111111),(UC_X86_REG_EBX,0x22222222),(UC_X86_REG_ECX,0x33333333),(UC_X86_REG_EDX,0x44444444),
                          (UC_X86_REG_ESI,0x55555555),(UC_X86_REG_EDI,0x66666666),(UC_X86_REG_EBP,0x77777777),(UC_X86_REG_ESP,STACK_TOP),(UC_X86_REG_EFLAGS,0x202)):
            cpu.reg_write(reg,value)
        w32(STACK_TOP,RETURN_SENTINEL)
        try:cpu.emu_start(address,RETURN_SENTINEL,timeout=120000000,count=200000000)
        except UcError as exc:
            error=f'initialiser {address:#x} faulted: {exc}'+(f' at {faults[-1][0]:#x} (eip {faults[-1][1]:#x})' if faults else '')+' recent blocks '+' '.join(hex(x) for x in recent);break
        except SystemExit as exc:error=f'initialiser {address:#x}: {exc}';break
        if cpu.reg_read(UC_X86_REG_EIP)!=RETURN_SENTINEL:error=f'initialiser {address:#x} did not return';break
        done.append(hex(address))
    out=ROOT/'private/analysis/static_init';out.mkdir(parents=True,exist_ok=True)
    (out/'trace.json').write_text(json.dumps({'input_sha256':EXPECTED,'completed':done,'error':error,'api_counts':dict(state['counts']),
        'unsupported_calls':state['calls'],'executed_blocks':sorted(hex(b) for b in blocks)},indent=1)+'\n',encoding='utf-8')
    print(len(done),'of',len(inits),'initialisers completed;',len(blocks),'executed blocks; APIs',dict(state['counts']))
    if error:print('STOP:',error)
if __name__=='__main__':main()
