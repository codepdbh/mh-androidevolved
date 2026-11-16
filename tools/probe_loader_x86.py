"""x86 reference for the isolated slot-loader test (tests/loader_native.c).

Runs the real .text of the verified executable in Unicorn from 0x605750 with
the same synthetic memory as the C harness. The game's pool allocator runs for real;
only the CRT malloc providing its arena is a stub; the read-only CreateFileA/ReadFile/
CloseHandle subset is emulated in Python over in-memory files, with the same
handle numbering as runtime/readonly_handles (first handle 0x40000010).
Does not launch the game. Output: private/analysis/loader/x86_reference.json.
"""
import hashlib,json,struct,sys,zlib
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX,UC_X86_REG_EBX,UC_X86_REG_ECX,UC_X86_REG_EDX,UC_X86_REG_ESI,
    UC_X86_REG_EDI,UC_X86_REG_EBP,UC_X86_REG_ESP,UC_X86_REG_EIP,UC_X86_REG_EFLAGS)
from inspect_entrypoint import ROOT,GAME,EXPECTED
REGS={'eax':UC_X86_REG_EAX,'ebx':UC_X86_REG_EBX,'ecx':UC_X86_REG_ECX,'edx':UC_X86_REG_EDX,'esi':UC_X86_REG_ESI,
      'edi':UC_X86_REG_EDI,'ebp':UC_X86_REG_EBP,'esp':UC_X86_REG_ESP,'eflags':UC_X86_REG_EFLAGS}
BLOCK_SIZES=(4,16,1,64,3,128,8);FILE_SIZES=(224,225,100,None)
POOL,ARENA_SIZE=0x67d000,0x8000
GLOBAL_BASE,GLOBAL_SIZE,CS,THREAD=0x8c0000,0x40000,0x828120,0x1234
def files():
    out={}
    for s,size in enumerate(FILE_SIZES):
        if size is not None:out[f'data/save/slot{s}.bin']=bytes((i*13+7+s)&255 for i in range(size))
    return out
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    pe=pefile.PE(data=data,fast_load=True);base=pe.OPTIONAL_HEADER.ImageBase
    text=[s for s in pe.sections if s.VirtualAddress<=0x605750-base<s.VirtualAddress+s.Misc_VirtualSize]
    if len(text)!=1:raise SystemExit('code section not found')
    text=text[0];code=text.get_data()[:text.Misc_VirtualSize];code_start=base+text.VirtualAddress
    if code_start+len(code)>0x7d0000:raise SystemExit('code section overlaps synthetic data')
    report=json.loads((ROOT/'private/analysis/candidate_time/dependencies/loader_strings_report.json').read_text())
    if report['input_sha256']!=EXPECTED:raise SystemExit('lift report does not match executable')
    for item in report['items']:
        start,end=(int(x,16) for x in item['range'])
        if hashlib.sha256(code[start-code_start:end-code_start]).hexdigest()!=item['bytes_sha256']:raise SystemExit('translated function bytes differ')
    content=files();cases=[]
    heap_table=pe.get_data(0x7e9ee8-base,28)
    for k in range(16):
        scenario,alignment=k%4,k//4
        cpu=Uc(UC_ARCH_X86,UC_MODE_32);cpu.mem_map(0x400000,0x500000);cpu.mem_write(code_start,code)
        for stub in (0x800300,0x800400,0x800500,0x800600,0x800700,0x800800):cpu.mem_write(stub,b'\xc3')
        w32=lambda a,v:cpu.mem_write(a,struct.pack('<I',v&0xffffffff))
        r32=lambda a:struct.unpack('<I',cpu.mem_read(a,4))[0]
        w32(0x81b37c,0x800400);w32(0x81b374,0x800300);w32(0x81b370,0x800500)
        w32(0x81b3e4,0x800600);w32(0x81b3e8,0x800700);w32(0x81b40c,0x800800)
        cpu.mem_write(0x7e9ee8,heap_table)  # same 7 real dwords as heap_data.h
        for i in range(0,24,4):w32(CS+i,0)
        w32(CS+4,0xffffffff)
        cpu.mem_write(0x831000,b'data\\\0');w32(0x8302ac,0x831000);cpu.mem_write(0x8302b0,struct.pack('<hh',5,0))
        cpu.mem_write(0x7d7d88,b'save\\\0')
        for i in range(4):cpu.mem_write(0x7d7c10+32*i,f'slot{i}.bin'.encode()+b'\0')
        for i in range(4):w32(0x830000+i*84+0xc,0x1000+i)
        state={'open':{},'next_generation':1,'api':[0,0,0],'mem':[0,0,0],'global_next':GLOBAL_BASE}
        def finish(ret_expected,args,value):
            esp=cpu.reg_read(UC_X86_REG_ESP);ret=r32(esp)
            if ret!=ret_expected:raise SystemExit(f'unexpected API return address {ret:#x}')
            cpu.reg_write(UC_X86_REG_EAX,value);cpu.reg_write(UC_X86_REG_ESP,esp+4+4*args);cpu.reg_write(UC_X86_REG_EIP,ret)
        def hook(uc,address,size,user):
            esp=cpu.reg_read(UC_X86_REG_ESP)
            if address==0x800400:   # CreateFileA, observed read-only subset
                state['api'][0]+=1;name=b''
                p=r32(esp+4)
                while len(name)<260:
                    c=bytes(cpu.mem_read(p+len(name),1))
                    if c==b'\0':break
                    name+=c
                args=[r32(esp+4*i) for i in range(2,8)];handle=0xffffffff
                key=name.decode('latin-1').replace('\\','/')
                if args==[0x80000000,0,0,3,0,0] and key in content and not state['open']:
                    handle=0x40000000|(state['next_generation']<<4)|0;state['open'][handle]=[content[key],0]
                finish(0x60fee2,7,handle)
            elif address==0x800300: # ReadFile, synchronous, no OVERLAPPED
                state['api'][1]+=1
                h,buf,n,out,ovl=(r32(esp+4*i) for i in range(1,6))
                w32(out,0)
                if ovl or h not in state['open']:finish(0x60ff76,5,0);return
                body,pos=state['open'][h];chunk=body[pos:pos+n]
                cpu.mem_write(buf,chunk);state['open'][h][1]=pos+len(chunk);w32(out,len(chunk));finish(0x60ff76,5,1)
            elif address==0x800500: # CloseHandle
                state['api'][2]+=1;h=r32(esp+4);ok=h in state['open']
                if ok:del state['open'][h];state['next_generation']+=1
                finish(0x60ff51,1,1 if ok else 0)
            elif address in (0x800600,0x800700):  # Enter/LeaveCriticalSection, as runtime/win32_memory.c
                enter=address==0x800600;state['mem'][0 if enter else 1]+=1;cs=r32(esp+4)
                lock,rec,owner=r32(cs+4),r32(cs+8),r32(cs+12)
                if enter:
                    if rec and owner!=THREAD:raise SystemExit('would block')
                    w32(cs+4,lock+1);w32(cs+8,rec+1);w32(cs+12,THREAD)
                else:
                    if not rec or owner!=THREAD:raise SystemExit('leave by non-owner')
                    w32(cs+4,lock-1);w32(cs+8,rec-1);w32(cs+12,0 if rec==1 else THREAD)
                cpu.reg_write(UC_X86_REG_ESP,esp+8);cpu.reg_write(UC_X86_REG_EIP,r32(esp))
                if r32(esp)!=(0x610bee if enter else 0x610c08):raise SystemExit('unexpected critical-section caller')
            elif address==0x800800:  # GlobalAlloc, as runtime/win32_memory.c
                state['mem'][2]+=1;flags,size=r32(esp+4),r32(esp+8);result=0
                start=(state['global_next']+7)&~7;size=size or 1
                if not flags&~0x40 and start+size<=GLOBAL_BASE+GLOBAL_SIZE:
                    cpu.mem_write(start,bytes(size));state['global_next']=start+size;result=start
                finish(0x64a490,2,result)
        cpu.hook_add(UC_HOOK_CODE,hook,begin=0x800300,end=0x800800)
        # The game's pool constructor; its arena now comes from the game's heap and GlobalAlloc.
        for name,value in [('eax',0),('ebx',0),('ecx',POOL),('edx',0),('esi',0),('edi',0),('ebp',0),('esp',0x880000),('eflags',2)]:cpu.reg_write(REGS[name],value)
        w32(0x880000,0x8f0000);w32(0x880004,ARENA_SIZE)
        cpu.emu_start(0x4010b0,0x8f0000,timeout=2000000,count=500000)
        if cpu.reg_read(UC_X86_REG_EIP)!=0x8f0000 or cpu.reg_read(UC_X86_REG_ESP)!=0x880008:raise SystemExit('pool constructor did not return')
        sp=0x880000+alignment
        for name,value in [('eax',0x11111111),('ebx',0x22222222),('ecx',0x830000),('edx',0x33333333),('esi',0x44444444),
                           ('edi',0x55555555),('ebp',0x66666666),('esp',sp),('eflags',2)]:cpu.reg_write(REGS[name],value)
        w32(sp,0x8f0000);w32(sp+4,scenario)
        for j in range(7):w32(sp+8+8*j,0x840000+0x100*j);w32(sp+12+8*j,BLOCK_SIZES[j])
        cpu.emu_start(0x605750,0x8f0000,timeout=2000000,count=200000)
        if cpu.reg_read(UC_X86_REG_EIP)!=0x8f0000:raise SystemExit('loader did not return')
        cases.append({'scenario':scenario,'alignment':alignment,'registers':{n:cpu.reg_read(r) for n,r in REGS.items()},'api':state['api'],
                      'stack_hex':bytes(cpu.mem_read(0x87fe00,0x300)).hex(),'object_hex':bytes(cpu.mem_read(0x830000,0x180)).hex(),
                      'buffers_hex':bytes(cpu.mem_read(0x840000,0x700)).hex(),'pool_hex':bytes(cpu.mem_read(POOL,0x1268)).hex(),
                      'mem_api':state['mem'],'global_next':state['global_next'],'cs_hex':bytes(cpu.mem_read(CS,24)).hex(),
                      'bss_crc':zlib.crc32(bytes(cpu.mem_read(0x81e000,0x8296d4-0x81e000))),
                      'global_crc':zlib.crc32(bytes(cpu.mem_read(GLOBAL_BASE,state['global_next']-GLOBAL_BASE))),'end':''})
    out=ROOT/'private/analysis/loader';out.mkdir(parents=True,exist_ok=True)
    (out/'x86_reference.json').write_text(json.dumps({'input_sha256':EXPECTED,'strings_unit_sha256':report['unit_sha256'],
        'scope':'0x605750 with real .text: loader, pool allocator and heap; emulated read-only file API and memory shims','cases':cases},indent=2)+'\n',encoding='utf-8')
    print(len(cases),'x86 loader reference cases; results',[c['registers']['eax'] for c in cases[:4]],'api',[c['api'] for c in cases[:4]])
if __name__=='__main__':main()
