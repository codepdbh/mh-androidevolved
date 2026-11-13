"""Isolated x86 reference for the indirect dependency's zero-argument branch."""
import hashlib,json,struct
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32
from unicorn.x86_const import UC_X86_REG_EAX,UC_X86_REG_EBX,UC_X86_REG_ECX,UC_X86_REG_EDX,UC_X86_REG_ESI,UC_X86_REG_EDI,UC_X86_REG_EBP,UC_X86_REG_ESP,UC_X86_REG_EIP,UC_X86_REG_EFLAGS
from inspect_entrypoint import ROOT,GAME,EXPECTED
REGS={'eax':UC_X86_REG_EAX,'ebx':UC_X86_REG_EBX,'ecx':UC_X86_REG_ECX,'edx':UC_X86_REG_EDX,'esi':UC_X86_REG_ESI,'edi':UC_X86_REG_EDI,'ebp':UC_X86_REG_EBP,'esp':UC_X86_REG_ESP,'eflags':UC_X86_REG_EFLAGS}
def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    base=ROOT/'private/analysis/candidate_time/dependencies';report=json.loads((base/'indirect_report.json').read_text())
    if report['address']!='0x604dc0':raise SystemExit('unexpected candidate')
    pe=pefile.PE(data=data,fast_load=True);code=pe.get_data(0x604dc0-pe.OPTIONAL_HEADER.ImageBase,0x90)
    if len(code)!=0x90:raise SystemExit('incomplete code')
    cases=[]
    for argument in (0,0x12345678,0xffffffff):
        for alignment in range(4):
            cpu=Uc(UC_ARCH_X86,UC_MODE_32);cpu.mem_map(0x400000,0x500000);cpu.mem_write(0x604dc0,code)
            for a in (0x800200,0x800210):cpu.mem_write(a,b'\xc3')
            for a,v in ((0x736db8,0x820000),(0x82000c,0x821000),(0x821000,0x822000),(0x822028,0x800200),(0x822024,0x800210),(0x725a54,0x860000),(0x725a4c,0x860100)):
                cpu.mem_write(a,struct.pack('<I',v))
            esp=0x880000+alignment;cpu.mem_write(esp,struct.pack('<III',0x8f0000,argument,0))
            for n,v in [('eax',0x11111111),('ebx',0x22222222),('ecx',0x870000),('edx',0x33333333),('esi',0x44444444),('edi',0x55555555),('ebp',0x66666666),('esp',esp),('eflags',2)]:cpu.reg_write(REGS[n],v)
            cpu.emu_start(0x604dc0,0x8f0000,timeout=200000,count=1000)
            if cpu.reg_read(UC_X86_REG_EIP)!=0x8f0000:raise SystemExit('candidate did not return')
            cases.append({'argument':argument,'alignment':alignment,'registers':{n:cpu.reg_read(r) for n,r in REGS.items()},
                'stack_hex':bytes(cpu.mem_read(0x87ffe0,0x30)).hex(),'object_hex':bytes(cpu.mem_read(0x870000,0x20)).hex(),
                'global_a':struct.unpack('<I',cpu.mem_read(0x725a54,4))[0],'global_b':struct.unpack('<I',cpu.mem_read(0x725a4c,4))[0]})
    (base/'x86_zero_reference.json').write_text(json.dumps({'input_sha256':EXPECTED,'candidate_source_sha256':report['source_sha256'],
        'scope':'isolated zero-argument branch; synthetic virtual methods','cases':cases},indent=2)+'\n',encoding='utf-8')
    print(len(cases),'isolated zero-argument branch cases recorded')
if __name__=='__main__':main()
