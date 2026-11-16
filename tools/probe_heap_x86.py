"""x86 reference for tests/heap_native.c: the game's own heap (malloc 0x610be0) in Unicorn.

Runs the verified executable's .text; GlobalAlloc and Enter/LeaveCriticalSection
are emulated in Python with exactly the semantics of runtime/win32_memory.c.
Output: private/analysis/heap/x86_reference.json.
"""
import hashlib,json,struct,zlib
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX,UC_X86_REG_EBX,UC_X86_REG_ECX,UC_X86_REG_EDX,UC_X86_REG_ESI,
    UC_X86_REG_EDI,UC_X86_REG_EBP,UC_X86_REG_ESP,UC_X86_REG_EIP,UC_X86_REG_EFLAGS)
from inspect_entrypoint import ROOT,GAME,EXPECTED
REGS={'eax':UC_X86_REG_EAX,'ebx':UC_X86_REG_EBX,'ecx':UC_X86_REG_ECX,'edx':UC_X86_REG_EDX,'esi':UC_X86_REG_ESI,
      'edi':UC_X86_REG_EDI,'ebp':UC_X86_REG_EBP,'esp':UC_X86_REG_ESP,'eflags':UC_X86_REG_EFLAGS}
GLOBAL_BASE,GLOBAL_SIZE,CS,THREAD=0x1000000,0x1000000,0x828120,0x1234
SIZES=(1,7,16,24,100,200,512,1000,1024,4000,4096,8000,16384,30000,65536,100000)
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    pe=pefile.PE(data=data,fast_load=True);base=pe.OPTIONAL_HEADER.ImageBase
    text=[s for s in pe.sections if s.Name.rstrip(b'\0')==b'.text'][0]
    code=text.get_data()[:text.Misc_VirtualSize];code_start=base+text.VirtualAddress
    report=json.loads((ROOT/'private/analysis/heap/heap_report.json').read_text())
    if report['input_sha256']!=EXPECTED:raise SystemExit('lift report does not match executable')
    for item in report['items']:
        start,end=(int(x,16) for x in item['range'])
        if hashlib.sha256(code[start-code_start:end-code_start]).hexdigest()!=item['bytes_sha256']:raise SystemExit('translated function bytes differ')
    cases=[]
    for k in range(16):
        cpu=Uc(UC_ARCH_X86,UC_MODE_32);cpu.mem_map(0x400000,0x1c00000);cpu.mem_write(code_start,code)
        for stub in (0x800600,0x800700,0x800800):cpu.mem_write(stub,b'\xc3')
        w32=lambda a,v:cpu.mem_write(a,struct.pack('<I',v&0xffffffff))
        r32=lambda a:struct.unpack('<I',cpu.mem_read(a,4))[0]
        table=pe.get_data(0x7e9ee8-base,28);cpu.mem_write(0x7e9ee8,table)  # same 7 real dwords as heap_data.h
        w32(0x81b3e4,0x800600);w32(0x81b3e8,0x800700);w32(0x81b40c,0x800800)
        for i in range(0,24,4):w32(CS+i,0)
        w32(CS+4,0xffffffff)
        state={'next':GLOBAL_BASE,'api':[0,0,0]}
        def ret(expected,args):
            esp=cpu.reg_read(UC_X86_REG_ESP)
            if r32(esp)!=expected:raise SystemExit(f'unexpected API return address {r32(esp):#x}')
            cpu.reg_write(UC_X86_REG_ESP,esp+4+4*args);cpu.reg_write(UC_X86_REG_EIP,expected)
        def hook(uc,address,size,user):
            esp=cpu.reg_read(UC_X86_REG_ESP)
            if address in (0x800600,0x800700):
                enter=address==0x800600;state['api'][0 if enter else 1]+=1;cs=r32(esp+4)
                lock,rec,owner=r32(cs+4),r32(cs+8),r32(cs+12)
                if enter:
                    if rec and owner!=THREAD:raise SystemExit('would block')
                    w32(cs+4,lock+1);w32(cs+8,rec+1);w32(cs+12,THREAD)
                else:
                    if not rec or owner!=THREAD:raise SystemExit('leave by non-owner')
                    w32(cs+4,lock-1);w32(cs+8,rec-1);w32(cs+12,0 if rec==1 else THREAD)
                ret(0x610bee if enter else 0x610c08,1)
            elif address==0x800800:
                state['api'][2]+=1;flags,size=r32(esp+4),r32(esp+8);result=0
                start=(state['next']+7)&~7;size=size or 1
                if not flags&~0x40 and start+size<=GLOBAL_BASE+GLOBAL_SIZE:
                    cpu.mem_write(start,bytes(size));state['next']=start+size;result=start
                cpu.reg_write(UC_X86_REG_EAX,result);ret(0x64a490,2)
        cpu.hook_add(UC_HOOK_CODE,hook,begin=0x800600,end=0x800800)
        sp=0x880000+k%4;x=(0x2468ace+k*0x9e3779b9)&0xffffffff;results=[]
        for op in range(40):
            x=(x*1103515245+12345)&0xffffffff;size=SIZES[(x>>8)%16]
            for name,value in [('eax',0x11111111),('ebx',0x22222222),('ecx',0x33333333),('edx',0x44444444),('esi',0x55555555),
                               ('edi',0x66666666),('ebp',0x77777777),('esp',sp),('eflags',2)]:cpu.reg_write(REGS[name],value)
            cpu.mem_write(sp,struct.pack('<II',0x8f0000,size))
            cpu.emu_start(0x610be0,0x8f0000,timeout=20000000,count=5000000)
            if cpu.reg_read(UC_X86_REG_EIP)!=0x8f0000 or cpu.reg_read(UC_X86_REG_ESP)!=sp+4:raise SystemExit('malloc did not return cleanly')
            p=cpu.reg_read(UC_X86_REG_EAX);results.append(p)
            if p:cpu.mem_write(p,bytes((op*7+i)&255 for i in range(min(size,32))))
        cases.append({'case':k,'results':results,'registers':{n:cpu.reg_read(r) for n,r in REGS.items()},'api':state['api'],'global_next':state['next'],
                      'stack_hex':bytes(cpu.mem_read(0x87fe00,0x300)).hex(),'cs_hex':bytes(cpu.mem_read(CS,24)).hex(),
                      'bss_crc':zlib.crc32(bytes(cpu.mem_read(0x81e000,0x8296d4-0x81e000))),
                      'global_crc':zlib.crc32(bytes(cpu.mem_read(GLOBAL_BASE,state['next']-GLOBAL_BASE)))})
    out=ROOT/'private/analysis/heap';out.mkdir(parents=True,exist_ok=True)
    (out/'x86_reference.json').write_text(json.dumps({'input_sha256':EXPECTED,'unit_sha256':report['unit_sha256'],'cases':cases},indent=2)+'\n',encoding='utf-8')
    ok=sum(1 for c in cases for r in c['results'] if r);fail=sum(1 for c in cases for r in c['results'] if not r)
    print(len(cases),'x86 heap cases;',ok,'successful mallocs,',fail,'failed; GlobalAlloc calls',sum(c['api'][2] for c in cases),
          '; max arena used',hex(max(c['global_next'] for c in cases)-GLOBAL_BASE))
if __name__=='__main__':main()
