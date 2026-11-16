"""x86 reference for the isolated slot-loader test (tests/loader_native.c).

Runs the real .text of the verified executable in Unicorn from 0x605750 with
the same synthetic memory as the C harness. The game's pool allocator runs for real;
only the CRT malloc providing its arena is a stub; the read-only CreateFileA/ReadFile/
CloseHandle subset is emulated in Python over in-memory files, with the same
handle numbering as runtime/readonly_handles (first handle 0x40000010).
Does not launch the game. Output: private/analysis/loader/x86_reference.json.
"""
import hashlib,json,struct,sys
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX,UC_X86_REG_EBX,UC_X86_REG_ECX,UC_X86_REG_EDX,UC_X86_REG_ESI,
    UC_X86_REG_EDI,UC_X86_REG_EBP,UC_X86_REG_ESP,UC_X86_REG_EIP,UC_X86_REG_EFLAGS)
from inspect_entrypoint import ROOT,GAME,EXPECTED
REGS={'eax':UC_X86_REG_EAX,'ebx':UC_X86_REG_EBX,'ecx':UC_X86_REG_ECX,'edx':UC_X86_REG_EDX,'esi':UC_X86_REG_ESI,
      'edi':UC_X86_REG_EDI,'ebp':UC_X86_REG_EBP,'esp':UC_X86_REG_ESP,'eflags':UC_X86_REG_EFLAGS}
BLOCK_SIZES=(4,16,1,64,3,128,8);FILE_SIZES=(224,225,100,None)
POOL,ARENA,ARENA_SIZE=0x67d000,0x8c0000,0x8000
# CRT malloc double for the pool arena: mov eax,ARENA; ret
MALLOC=bytes([0xb8])+struct.pack('<I',ARENA)+bytes([0xc3])
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
    for k in range(16):
        scenario,alignment=k%4,k//4
        cpu=Uc(UC_ARCH_X86,UC_MODE_32);cpu.mem_map(0x400000,0x500000);cpu.mem_write(code_start,code)
        cpu.mem_write(0x610be0,MALLOC)
        for stub in (0x800300,0x800400,0x800500):cpu.mem_write(stub,b'\xc3')
        w32=lambda a,v:cpu.mem_write(a,struct.pack('<I',v&0xffffffff))
        r32=lambda a:struct.unpack('<I',cpu.mem_read(a,4))[0]
        w32(0x81b37c,0x800400);w32(0x81b374,0x800300);w32(0x81b370,0x800500)
        cpu.mem_write(0x831000,b'data\\\0');w32(0x8302ac,0x831000);cpu.mem_write(0x8302b0,struct.pack('<hh',5,0))
        cpu.mem_write(0x7d7d88,b'save\\\0')
        for i in range(4):cpu.mem_write(0x7d7c10+32*i,f'slot{i}.bin'.encode()+b'\0')
        for i in range(4):w32(0x830000+i*84+0xc,0x1000+i)
        # The game's pool constructor over the arena, as the static initialiser does.
        for name,value in [('eax',0),('ebx',0),('ecx',POOL),('edx',0),('esi',0),('edi',0),('ebp',0),('esp',0x880000),('eflags',2)]:cpu.reg_write(REGS[name],value)
        w32(0x880000,0x8f0000);w32(0x880004,ARENA_SIZE)
        cpu.emu_start(0x4010b0,0x8f0000,timeout=2000000,count=200000)
        if cpu.reg_read(UC_X86_REG_EIP)!=0x8f0000 or cpu.reg_read(UC_X86_REG_ESP)!=0x880008:raise SystemExit('pool constructor did not return')
        sp=0x880000+alignment
        for name,value in [('eax',0x11111111),('ebx',0x22222222),('ecx',0x830000),('edx',0x33333333),('esi',0x44444444),
                           ('edi',0x55555555),('ebp',0x66666666),('esp',sp),('eflags',2)]:cpu.reg_write(REGS[name],value)
        w32(sp,0x8f0000);w32(sp+4,scenario)
        for j in range(7):w32(sp+8+8*j,0x840000+0x100*j);w32(sp+12+8*j,BLOCK_SIZES[j])
        state={'open':{},'next_generation':1,'api':[0,0,0]}
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
        cpu.hook_add(UC_HOOK_CODE,hook,begin=0x800300,end=0x800500)
        cpu.emu_start(0x605750,0x8f0000,timeout=2000000,count=200000)
        if cpu.reg_read(UC_X86_REG_EIP)!=0x8f0000:raise SystemExit('loader did not return')
        cases.append({'scenario':scenario,'alignment':alignment,'registers':{n:cpu.reg_read(r) for n,r in REGS.items()},'api':state['api'],
                      'stack_hex':bytes(cpu.mem_read(0x87fe00,0x300)).hex(),'object_hex':bytes(cpu.mem_read(0x830000,0x180)).hex(),
                      'buffers_hex':bytes(cpu.mem_read(0x840000,0x700)).hex(),'heap_hex':bytes(cpu.mem_read(POOL,0x1268)).hex()+bytes(cpu.mem_read(ARENA,ARENA_SIZE)).hex()})
    out=ROOT/'private/analysis/loader';out.mkdir(parents=True,exist_ok=True)
    (out/'x86_reference.json').write_text(json.dumps({'input_sha256':EXPECTED,'strings_unit_sha256':report['unit_sha256'],
        'scope':'0x605750 with real .text; pool allocator doubles; emulated read-only file API','cases':cases},indent=2)+'\n',encoding='utf-8')
    print(len(cases),'x86 loader reference cases; results',[c['registers']['eax'] for c in cases[:4]],'api',[c['api'] for c in cases[:4]])
if __name__=='__main__':main()
