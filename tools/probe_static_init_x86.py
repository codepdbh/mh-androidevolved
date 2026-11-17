"""x86 reference for tests/static_init_native.c (boot phase 1) in Unicorn.

Maps the verified executable exactly like runtime/pe32_image.c (zeroed image,
headers, then each section's raw data at its RVA), answers CPUID with the
virtual CPU of recomp/virtual_cpu.h, emulates the memory API shims of
runtime/win32_memory.c and runs the same static initialisers in .CRT order.
Output: private/analysis/static_init/x86_reference.json.
"""
import hashlib,json,struct,zlib
import pefile
from unicorn import Uc,UcError,UC_ARCH_X86,UC_MODE_32,UC_HOOK_INSN,UC_HOOK_MEM_INVALID,UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX,UC_X86_REG_EBX,UC_X86_REG_ECX,UC_X86_REG_EDX,UC_X86_REG_ESI,
    UC_X86_REG_EDI,UC_X86_REG_EBP,UC_X86_REG_ESP,UC_X86_REG_EIP,UC_X86_REG_EFLAGS,UC_X86_INS_CPUID)
from inspect_entrypoint import ROOT,GAME,EXPECTED
GUEST_END,STACK_TOP,RETURN_SENTINEL,API_BASE=0x6200000,0x1800000,0x1f00000,0x1e00000
GLOBAL_BASE,GLOBAL_SIZE,CS,THREAD=0x2000000,0x4100000,0x828120,0x1234
def virtual_cpuid(uc,user):
    leaf=uc.reg_read(UC_X86_REG_EAX);a=b=c=d=0
    if leaf==0:a,b,d,c=1,0x756e6547,0x49656e69,0x6c65746e
    elif leaf==1:a,d=0x673,0x1
    elif leaf==0x80000000:a=0x80000000
    for reg,value in ((UC_X86_REG_EAX,a),(UC_X86_REG_EBX,b),(UC_X86_REG_ECX,c),(UC_X86_REG_EDX,d)):uc.reg_write(reg,value)
    return True  # instruction handled; skip Unicorn's own CPUID
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    pe=pefile.PE(data=data,fast_load=True);opt=pe.OPTIONAL_HEADER
    report=json.loads((ROOT/'private/analysis/static_init/static_init_report.json').read_text())
    inits=[int(x,16) for x in report['initializers']]
    cpu=Uc(UC_ARCH_X86,UC_MODE_32);cpu.mem_map(0x400000,GUEST_END-0x400000)
    image=bytearray(opt.SizeOfImage);image[:opt.SizeOfHeaders]=data[:opt.SizeOfHeaders]
    for s in pe.sections:
        if s.SizeOfRawData:image[s.VirtualAddress:s.VirtualAddress+s.SizeOfRawData]=data[s.PointerToRawData:s.PointerToRawData+s.SizeOfRawData]
    cpu.mem_write(opt.ImageBase,bytes(image))
    w32=lambda a,v:cpu.mem_write(a,struct.pack('<I',v&0xffffffff))
    r32=lambda a:struct.unpack('<I',cpu.mem_read(a,4))[0]
    for slot,offset in ((0x81b3e4,0x100),(0x81b3e8,0x200),(0x81b40c,0x300)):w32(slot,API_BASE+offset);cpu.mem_write(API_BASE+offset,b'\xc3')
    for i in range(0,24,4):w32(CS+i,0)
    w32(CS+4,0xffffffff)
    state={'mem':[0,0,0],'next':GLOBAL_BASE}
    def api(uc,address,size,user):
        esp=cpu.reg_read(UC_X86_REG_ESP);ret=r32(esp)
        if address in (API_BASE+0x100,API_BASE+0x200):
            enter=address==API_BASE+0x100;state['mem'][0 if enter else 1]+=1;cs=r32(esp+4)
            lock,rec,owner=r32(cs+4),r32(cs+8),r32(cs+12)
            if enter:
                if rec and owner!=THREAD:raise SystemExit('would block')
                w32(cs+4,lock+1);w32(cs+8,rec+1);w32(cs+12,THREAD)
            else:
                if not rec or owner!=THREAD:raise SystemExit('leave by non-owner')
                w32(cs+4,lock-1);w32(cs+8,rec-1);w32(cs+12,0 if rec==1 else THREAD)
            cpu.reg_write(UC_X86_REG_ESP,esp+8)
        elif address==API_BASE+0x300:
            state['mem'][2]+=1;flags,size=r32(esp+4),r32(esp+8);result=0
            start=(state['next']+7)&~7;size=size or 1
            if not flags&~0x40 and start+size<=GLOBAL_BASE+GLOBAL_SIZE:
                cpu.mem_write(start,bytes(size));state['next']=start+size;result=start
            cpu.reg_write(UC_X86_REG_EAX,result);cpu.reg_write(UC_X86_REG_ESP,esp+12)
        else:return
        cpu.reg_write(UC_X86_REG_EIP,ret)
    cpu.hook_add(UC_HOOK_CODE,api,begin=API_BASE+0x100,end=API_BASE+0x300)
    cpu.hook_add(UC_HOOK_INSN,virtual_cpuid,None,1,0,UC_X86_INS_CPUID)
    faults=[]
    cpu.hook_add(UC_HOOK_MEM_INVALID,lambda uc,access,addr,size,value,user:faults.append((addr,uc.reg_read(UC_X86_REG_EIP))) or False)
    results=[]
    for address in inits:
        for reg,value in ((UC_X86_REG_EAX,0x11111111),(UC_X86_REG_EBX,0x22222222),(UC_X86_REG_ECX,0x33333333),(UC_X86_REG_EDX,0x44444444),
                          (UC_X86_REG_ESI,0x55555555),(UC_X86_REG_EDI,0x66666666),(UC_X86_REG_EBP,0x77777777),(UC_X86_REG_ESP,STACK_TOP),(UC_X86_REG_EFLAGS,0x202)):  # IF=1, as in any user-mode process
            cpu.reg_write(reg,value)
        w32(STACK_TOP,RETURN_SENTINEL)
        try:cpu.emu_start(address,RETURN_SENTINEL,timeout=60000000,count=50000000)
        except UcError as exc:
            detail=f' at {faults[-1][0]:#x} (eip {faults[-1][1]:#x})' if faults else ''
            raise SystemExit(f'initialiser {address:#x} faulted on x86: {exc}{detail}')
        if cpu.reg_read(UC_X86_REG_EIP)!=RETURN_SENTINEL or cpu.reg_read(UC_X86_REG_ESP)!=STACK_TOP+4:raise SystemExit(f'initialiser {address:#x} did not return cleanly')
        results.append([address]+[cpu.reg_read(r) for r in (UC_X86_REG_EAX,UC_X86_REG_EBX,UC_X86_REG_ECX,UC_X86_REG_EDX,UC_X86_REG_ESI,UC_X86_REG_EDI)])
    read=lambda a,n:bytes(cpu.mem_read(a,n))
    case={'image':[opt.ImageBase,opt.SizeOfImage,opt.AddressOfEntryPoint],'results':results,'mem_api':state['mem'],'global_next':state['next'],
          'data_crc':zlib.crc32(read(0x67d000,0x7ed4a0-0x67d000)),'bss_crc':zlib.crc32(read(0x81e000,0x8296d4-0x81e000)),
          'image_crc':zlib.crc32(read(0x400000,0xa18000-0x400000)),'stack_crc':zlib.crc32(read(STACK_TOP-0x2000,0x2004)),
          'global_crc':zlib.crc32(read(GLOBAL_BASE,state['next']-GLOBAL_BASE))}
    out=ROOT/'private/analysis/static_init'
    (out/'x86_reference.json').write_text(json.dumps({'input_sha256':EXPECTED,'unit_sha256':report['unit_sha256'],'cases':[case]},indent=2)+'\n',encoding='utf-8')
    changed=sum(1 for a,b in zip(image[0x27d000:0x3ed4a0],read(0x67d000,0x7ed4a0-0x67d000)) if a!=b)
    print(len(results),'initialisers ran on x86;',changed,'bytes of .data changed; memory API calls',state['mem'],'; GlobalAlloc used',hex(state['next']-GLOBAL_BASE))
if __name__=='__main__':main()
