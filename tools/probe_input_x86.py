"""Isolated input-candidate oracle with synthetic Win32/DirectInput doubles."""
import hashlib,json,struct
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_PROT_READ,UC_PROT_EXEC
from unicorn.x86_const import UC_X86_REG_EAX,UC_X86_REG_EBX,UC_X86_REG_ECX,UC_X86_REG_EDX,UC_X86_REG_ESI,UC_X86_REG_EDI,UC_X86_REG_EBP,UC_X86_REG_ESP,UC_X86_REG_EIP,UC_X86_REG_EFLAGS
from inspect_entrypoint import ROOT,GAME,EXPECTED

REGS={'eax':UC_X86_REG_EAX,'ebx':UC_X86_REG_EBX,'ecx':UC_X86_REG_ECX,'edx':UC_X86_REG_EDX,'esi':UC_X86_REG_ESI,'edi':UC_X86_REG_EDI,'ebp':UC_X86_REG_EBP,'esp':UC_X86_REG_ESP,'eflags':UC_X86_REG_EFLAGS}
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    base=ROOT/'private/analysis/candidate_input';report=json.loads((base/'report.json').read_text(encoding='utf-8'))
    if report['address']!='0x4c1ba0':raise SystemExit('unexpected candidate')
    pe=pefile.PE(data=data,fast_load=True);imagebase=pe.OPTIONAL_HEADER.ImageBase;cases=[]
    for scenario in ('success','failure','already'):
        cpu=Uc(UC_ARCH_X86,UC_MODE_32)
        for page in (0x100000,0x200000,0x210000,0x300000,0x4c1000,0x60f000,0x644000,0x736000,0x81b000):cpu.mem_map(page,0x10000 if page==0x100000 else 0x1000)
        for page in (0x4c1000,0x644000):
            code=pe.get_data(page-imagebase,0x1000)
            if len(code)!=0x1000:raise SystemExit('incomplete code page')
            cpu.mem_write(page,code);cpu.mem_protect(page,0x1000,UC_PROT_READ|UC_PROT_EXEC)
        # Test doubles only, no Windows or DirectInput APIs are invoked.
        cpu.mem_write(0x300000,b'\xb8'+struct.pack('<I',0x222000)+b'\xc2\x04\x00')
        mock=(b'\xb8\x05\x40\x00\x80\xc2\x14\x00' if scenario=='failure' else
              b'\x8b\x44\x24\x10\xc7\x00\x00\x00\x23\x00\x31\xc0\xc2\x14\x00')
        cpu.mem_write(0x300020,mock);cpu.mem_protect(0x300000,0x1000,UC_PROT_READ|UC_PROT_EXEC)
        cpu.mem_write(0x60f110,b'\xc3');cpu.mem_protect(0x60f000,0x1000,UC_PROT_READ|UC_PROT_EXEC)
        cpu.mem_write(0x81b3ac,struct.pack('<I',0x300000));cpu.mem_write(0x81b35c,struct.pack('<I',0x300020))
        cpu.mem_write(0x736db8,struct.pack('<I',0x200000));cpu.mem_write(0x20000c,struct.pack('<I',0x210000))
        cpu.mem_write(0x210020,struct.pack('<I',0x230000 if scenario=='already' else 0))
        esp=0x108000;cpu.mem_write(esp,struct.pack('<I',0x320000))
        for name,value in [('eax',0),('ebx',0x11111111),('ecx',0),('edx',0),('esi',0x22222222),('edi',0x33333333),('ebp',0x44444444),('esp',esp),('eflags',2)]:cpu.reg_write(REGS[name],value)
        cpu.emu_start(0x4c1ba0,0x320000,timeout=200000,count=5000)
        if cpu.reg_read(UC_X86_REG_EIP)!=0x320000:raise RuntimeError('candidate did not return within limits')
        cases.append({'scenario':scenario,'registers':{name:cpu.reg_read(reg) for name,reg in REGS.items()},
                      'stack_hex':bytes(cpu.mem_read(esp-64,80)).hex(),'config_hex':bytes(cpu.mem_read(0x210000,64)).hex()})
    expected=(0,0x80004005,0)
    if tuple(c['registers']['eax'] for c in cases)!=expected:raise SystemExit('unexpected synthetic results')
    (base/'x86_reference.json').write_text(json.dumps({'scope':'isolated x86, synthetic Win32 and DirectInput doubles; no device capture',
        'input_sha256':EXPECTED,'candidate_source_sha256':report['source_sha256'],'cases':cases},indent=2)+'\n',encoding='utf-8')
    print('3 synthetic DirectInput reference cases recorded; no input devices used')
if __name__=='__main__':main()
