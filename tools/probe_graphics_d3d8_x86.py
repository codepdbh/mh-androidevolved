"""x86 reference for tests/graphics_d3d8_native.c: 0x4c0830 in Unicorn over an
emulation of runtime/d3d8.c (same mode list, object layout and method semantics).
Output: private/analysis/graphics_d3d8/x86_reference.json.
"""
import hashlib,json,struct
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX,UC_X86_REG_EBX,UC_X86_REG_ECX,UC_X86_REG_EDX,UC_X86_REG_ESI,
    UC_X86_REG_EDI,UC_X86_REG_EBP,UC_X86_REG_ESP,UC_X86_REG_EIP,UC_X86_REG_EFLAGS)
from inspect_entrypoint import ROOT,GAME,EXPECTED
REGS={'eax':UC_X86_REG_EAX,'ebx':UC_X86_REG_EBX,'ecx':UC_X86_REG_ECX,'edx':UC_X86_REG_EDX,'esi':UC_X86_REG_ESI,
      'edi':UC_X86_REG_EDI,'ebp':UC_X86_REG_EBP,'esp':UC_X86_REG_ESP,'eflags':UC_X86_REG_EFLAGS}
D3D8_VA,HEAP=0x1e10000,0x1d00000
SIZES=((640,480),(800,600),(1024,768),(1280,720),(1280,960),(1920,1080));FORMATS=(22,23)
MODES=[(w,h,60,f) for (w,h) in SIZES for f in FORMATS]
ARGS=(3,1,1,2,1,4,2,4,3,6,7,6,6,4,2,7)
WIDTHS,HEIGHTS,DEPTHS=(640,1280,1920,1000),(480,720,1080,700),(16,24,32)
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    pe=pefile.PE(data=data,fast_load=True);base=pe.OPTIONAL_HEADER.ImageBase
    text=[s for s in pe.sections if s.Name.rstrip(b'\0')==b'.text'][0]
    report=json.loads((ROOT/'private/analysis/graphics_d3d8/graphics_d3d8_report.json').read_text())
    cases=[]
    for k in range(48):
        size,depth,adapter,alignment=k%4,(k//4)%3,(k//12)%2,k//24
        cpu=Uc(UC_ARCH_X86,UC_MODE_32);cpu.mem_map(0x10000,0x1ff0000)
        cpu.mem_write(base+text.VirtualAddress,text.get_data()[:text.Misc_VirtualSize])
        w32=lambda a,v:cpu.mem_write(a,struct.pack('<I',v&0xffffffff))
        r32=lambda a:struct.unpack('<I',cpu.mem_read(a,4))[0]
        # runtime/d3d8.c layout: vtable at the 16-aligned heap start, objects after it.
        vtable=HEAP;heap_next=HEAP+64
        for i in range(16):w32(vtable+4*i,D3D8_VA+4*i);cpu.mem_write(D3D8_VA+4*i,b'\xc3')
        state={'next':heap_next,'com':0}
        w32(0x735eb0,adapter)
        def hook(uc,address,size_,user):
            esp=cpu.reg_read(UC_X86_REG_ESP);ret=r32(esp)
            if address==0x64408c:   # Direct3DCreate8(SDKVersion)
                result=0
                if r32(esp+4)==220:
                    start=(state['next']+15)&~15;state['next']=start+16;w32(start,vtable);w32(start+4,1);result=start
                cpu.reg_write(UC_X86_REG_EAX,result);cpu.reg_write(UC_X86_REG_ESP,esp+8);cpu.reg_write(UC_X86_REG_EIP,ret);return
            if not D3D8_VA<=address<D3D8_VA+64:return
            method=(address-D3D8_VA)//4;a=[r32(esp+4+4*i) for i in range(ARGS[method])]
            if r32(a[0])!=vtable:raise SystemExit('bad this')
            if method==2:refs=max(r32(a[0]+4)-1,0);w32(a[0]+4,refs);result=refs
            elif method==1:refs=r32(a[0]+4)+1;w32(a[0]+4,refs);result=refs
            elif method==6:result=len(MODES) if a[1]==0 else 0
            elif method==7:
                if a[1]!=0 or a[2]>=len(MODES) or not a[3]:result=0x8876086c
                else:cpu.mem_write(a[3],struct.pack('<4I',*MODES[a[2]]));result=0
            else:raise SystemExit(f'method {method} not emulated')
            state['com']+=1
            cpu.reg_write(UC_X86_REG_EAX,result);cpu.reg_write(UC_X86_REG_ESP,esp+4+4*ARGS[method]);cpu.reg_write(UC_X86_REG_EIP,ret)
        cpu.hook_add(UC_HOOK_CODE,hook,begin=0x64408c,end=0x64408c);cpu.hook_add(UC_HOOK_CODE,hook,begin=D3D8_VA,end=D3D8_VA+64)
        sp=0x180000+alignment*4
        for name,value in [('eax',0x11111111),('ebx',0x22222222),('ecx',0x33333333),('edx',0x44444444),('esi',0x55555555),
                           ('edi',0x66666666),('ebp',0x77777777),('esp',sp),('eflags',0x202)]:cpu.reg_write(REGS[name],value)
        cpu.mem_write(sp,struct.pack('<4I',0x8f0000,WIDTHS[size],HEIGHTS[size],DEPTHS[depth]))
        cpu.emu_start(0x4c0830,0x8f0000,timeout=5000000,count=200000)
        if cpu.reg_read(UC_X86_REG_EIP)!=0x8f0000 or cpu.reg_read(UC_X86_REG_ESP)!=sp+4:raise SystemExit('candidate did not return cleanly')
        cases.append({'case':k,'registers':{n:cpu.reg_read(r) for n,r in REGS.items()},'com_calls':state['com'],
                      'stack_hex':bytes(cpu.mem_read(0x17fe00,0x300)).hex(),'heap_hex':bytes(cpu.mem_read(HEAP,0x60)).hex()})
    (ROOT/'private/analysis/graphics_d3d8/x86_reference.json').write_text(json.dumps({'input_sha256':EXPECTED,'unit_sha256':report['unit_sha256'],'cases':cases},indent=2)+'\n',encoding='utf-8')
    results=[c['registers']['eax'] for c in cases]
    print(len(cases),'cases; refresh results',sorted(set(results)),'; found',sum(1 for r in results if r==60),'not found',sum(1 for r in results if r==0xffffffff))
if __name__=='__main__':main()
