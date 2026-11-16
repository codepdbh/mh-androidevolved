"""x86 reference for tests/allocator_native.c: the game's real pool allocator in Unicorn.

Copies the verified executable's .text, replaces only the CRT malloc 0x610be0
with a stub equivalent to the C double, and replays the same deterministic
sequence of constructor/allocate/free calls. Output: private/analysis/allocator/x86_reference.json.
"""
import hashlib,json,struct
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32
from unicorn.x86_const import (UC_X86_REG_EAX,UC_X86_REG_EBX,UC_X86_REG_ECX,UC_X86_REG_EDX,UC_X86_REG_ESI,
    UC_X86_REG_EDI,UC_X86_REG_EBP,UC_X86_REG_ESP,UC_X86_REG_EIP,UC_X86_REG_EFLAGS)
from inspect_entrypoint import ROOT,GAME,EXPECTED
REGS={'eax':UC_X86_REG_EAX,'ebx':UC_X86_REG_EBX,'ecx':UC_X86_REG_ECX,'edx':UC_X86_REG_EDX,'esi':UC_X86_REG_ESI,
      'edi':UC_X86_REG_EDI,'ebp':UC_X86_REG_EBP,'esp':UC_X86_REG_ESP,'eflags':UC_X86_REG_EFLAGS}
POOL,ARENA,ARENA_SIZE=0x67d000,0x890000,0x30000
SIZES=(1,8,15,16,17,31,48,100,255,256,1000,2032,2048,3000,5000,0x3000)
# mov eax,[esp+4]; mov [0x8c0100],eax; mov eax,ARENA; ret   (CRT malloc double)
MALLOC=bytes.fromhex('8b442404')+bytes.fromhex('a300018c00')+b'\xb8'+struct.pack('<I',ARENA)+b'\xc3'
def fnv(data):
    h=1469598103934665603
    for b in data:h=((h^b)*1099511628211)&0xffffffffffffffff
    return f'{h:016x}'
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    pe=pefile.PE(data=data,fast_load=True);base=pe.OPTIONAL_HEADER.ImageBase
    text=[s for s in pe.sections if s.Name.rstrip(b'\0')==b'.text']
    if len(text)!=1:raise SystemExit('code section not found')
    text=text[0];code=text.get_data()[:text.Misc_VirtualSize];code_start=base+text.VirtualAddress
    if code_start+len(code)>POOL:raise SystemExit('code overlaps the pool object')
    report=json.loads((ROOT/'private/analysis/allocator/allocator_report.json').read_text())
    if report['input_sha256']!=EXPECTED:raise SystemExit('lift report does not match executable')
    for item in report['items']:
        start,end=(int(x,16) for x in item['range'])
        if hashlib.sha256(code[start-code_start:end-code_start]).hexdigest()!=item['bytes_sha256']:raise SystemExit('translated function bytes differ')
    cases=[]
    for k in range(16):
        alignment,zero_fill,seed_variant=k%4,(k//4)%2,k//8
        cpu=Uc(UC_ARCH_X86,UC_MODE_32);cpu.mem_map(0x400000,0x500000);cpu.mem_write(code_start,code);cpu.mem_write(0x610be0,MALLOC)
        cpu.mem_write(ARENA,b'\xcd'*ARENA_SIZE)
        r32=lambda a:struct.unpack('<I',cpu.mem_read(a,4))[0]
        sp=0x880000+alignment
        def call(fn,argument):
            for name,value in [('eax',0x11111111),('ebx',0x22222222),('ecx',POOL),('edx',0x33333333),('esi',0x44444444),
                               ('edi',0x55555555),('ebp',0x66666666),('esp',sp),('eflags',2)]:cpu.reg_write(REGS[name],value)
            cpu.mem_write(sp,struct.pack('<II',0x8f0000,argument))
            cpu.emu_start(fn,0x8f0000,timeout=5000000,count=2000000)
            if cpu.reg_read(UC_X86_REG_EIP)!=0x8f0000 or cpu.reg_read(UC_X86_REG_ESP)!=sp+8:raise SystemExit('call did not return cleanly')
            return cpu.reg_read(UC_X86_REG_EAX)
        call(0x4010b0,ARENA_SIZE)
        cpu.mem_write(0x67e264,bytes([zero_fill]))
        x=(0x1234567+k*0x9e3779b9+seed_variant)&0xffffffff;live=[];results=[]
        for op in range(60):
            x=(x*1103515245+12345)&0xffffffff
            if not live or (x>>16)%3!=0:
                size=SIZES[(x>>8)%16];p=call(0x401350,size);results.append(p)
                if p and len(live)<64:
                    live.append(p);cpu.mem_write(p,bytes((op+i)&255 for i in range(min(size,64))))
            else:
                i=(x>>4)%len(live);p=live[i];live[i]=live[-1];live.pop()
                call(0x401b00,p);results.append(0xF0000000|(p&0x0fffffff))
        cases.append({'case':k,'results':results,'registers':{n:cpu.reg_read(r) for n,r in REGS.items()},
                      'pool_hex':bytes(cpu.mem_read(POOL,0x1268)).hex(),'stack_hex':bytes(cpu.mem_read(0x87fe00,0x300)).hex(),
                      'arena_fnv':fnv(bytes(cpu.mem_read(ARENA,ARENA_SIZE))),'malloc_request':r32(0x8c0100)})
    out=ROOT/'private/analysis/allocator';out.mkdir(parents=True,exist_ok=True)
    (out/'x86_reference.json').write_text(json.dumps({'input_sha256':EXPECTED,'unit_sha256':report['unit_sha256'],
        'scope':'pool ctor/allocate/free with real .text; CRT malloc double','cases':cases},indent=2)+'\n',encoding='utf-8')
    allocs=sum(1 for c in cases for r in c['results'] if r and r>>28!=0xF);frees=sum(1 for c in cases for r in c['results'] if r>>28==0xF);fails=sum(1 for c in cases for r in c['results'] if r==0)
    print(len(cases),'x86 allocator cases;',allocs,'allocations,',frees,'frees,',fails,'failed allocations')
if __name__=='__main__':main()
