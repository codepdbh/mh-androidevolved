"""Run an isolated function candidate on synthetic data in Unicorn, never the PE as a program."""
import hashlib
import json
import struct
from pathlib import Path
import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_PROT_READ, UC_PROT_EXEC
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_EFLAGS, UC_X86_REG_FPCW, UC_X86_REG_FPSW, UC_X86_REG_FPTAG
from inspect_entrypoint import ROOT, GAME, EXPECTED

START=0x40a020
CODE_PAGE=0x40a000
SENTINEL=0x300000
STACK=0x100000
OBJECT=0x200000
ARRAY=0x210000
OUTPUT=0x220000
REGISTERS={'eax':UC_X86_REG_EAX,'ebx':UC_X86_REG_EBX,'ecx':UC_X86_REG_ECX,'edx':UC_X86_REG_EDX,'esi':UC_X86_REG_ESI,'edi':UC_X86_REG_EDI,'ebp':UC_X86_REG_EBP,'esp':UC_X86_REG_ESP,'eflags':UC_X86_REG_EFLAGS}

def probe(code, key, start, end, mode=0, skew=0, use_float=False):
    cpu=Uc(UC_ARCH_X86,UC_MODE_32)
    cpu.mem_map(CODE_PAGE,0x1000); cpu.mem_write(CODE_PAGE,code); cpu.mem_protect(CODE_PAGE,0x1000,UC_PROT_READ|UC_PROT_EXEC)
    for address in (STACK,OBJECT,ARRAY,OUTPUT): cpu.mem_map(address,0x10000)
    esp=STACK+0x8000+skew; obj_addr=OBJECT+skew; array_addr=ARRAY+skew; out_addr=OUTPUT+skew
    cpu.mem_write(esp,struct.pack('<5I',SENTINEL,key,out_addr,start,end))
    obj=bytearray(0x20);struct.pack_into('<I',obj,4,mode);struct.pack_into('<I',obj,12,array_addr);struct.pack_into('<H',obj,16,3)
    cpu.mem_write(obj_addr,bytes(obj))
    records=bytearray(24)
    for i,value in enumerate((10,20,30)):
        if use_float: struct.pack_into('<f',records,i*8,float(value))
        else: records[i*8]=value
    cpu.mem_write(array_addr,bytes(records));cpu.mem_write(out_addr,b'\xff\xff')
    for name,value in [('eax',0),('ebx',0x11111111),('edx',0),('esi',0x22222222),('edi',0x33333333),('ebp',0x44444444),('ecx',obj_addr),('esp',esp),('eflags',2)]: cpu.reg_write(REGISTERS[name],value)
    if use_float:
        cpu.reg_write(UC_X86_REG_FPCW,0x037f);cpu.reg_write(UC_X86_REG_FPSW,0);cpu.reg_write(UC_X86_REG_FPTAG,0xffff)
    cpu.emu_start(START,SENTINEL,timeout=200000,count=5000)
    if cpu.reg_read(UC_X86_REG_EIP)!=SENTINEL: raise RuntimeError('candidate did not return within limits')
    return {'key':key,'start':start,'end':end,'mode':mode,'skew':skew,'result':struct.unpack('<H',cpu.mem_read(out_addr,2))[0],
            'registers':{name:cpu.reg_read(reg) for name,reg in REGISTERS.items()},
            'stack_hex':bytes(cpu.mem_read(esp-16,36)).hex(),
            'object_hex':bytes(cpu.mem_read(obj_addr,32)).hex(),
            'array_hex':bytes(cpu.mem_read(array_addr,24)).hex(),
            'fp_top':(cpu.reg_read(UC_X86_REG_FPSW)>>11)&7 if use_float else None,
            'fp_status':cpu.reg_read(UC_X86_REG_FPSW) if use_float else None}

def main():
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED: raise SystemExit('unexpected executable hash')
    report=json.loads((ROOT/'private/analysis/candidate_deterministic/report.json').read_text(encoding='utf-8'))
    if report['address']!=hex(START): raise SystemExit('unexpected candidate')
    pe=pefile.PE(data=data,fast_load=True)
    code=pe.get_data(CODE_PAGE-pe.OPTIONAL_HEADER.ImageBase,0x1000)
    if len(code)!=0x1000: raise SystemExit('incomplete code page')
    cases=[probe(code,*args) for args in ((5,0,2),(20,0,2),(40,0,2),(20,2,1),(30,0,0))]
    expected=(0,1,3,3,2)
    actual=tuple(case['result'] for case in cases)
    if actual!=expected: raise SystemExit(f'x86 reference differs from expected synthetic cases: {actual}')
    cases.extend(probe(code,key,start,end,mode,skew)
                 for skew in (0,1,2,3) for mode in (0,1) for key in (0,5,10,15,20,25,30,35,255)
                 for start in (0,1,2) for end in (0,1,2))
    out=ROOT/'private/analysis/candidate_deterministic/x86_reference.json'
    out.write_text(json.dumps({'scope':'isolated Unicorn x86 reference; no translated code executed',
                               'input_sha256':EXPECTED, 'candidate_address':report['address'],
                               'candidate_source_sha256':report['source_sha256'], 'cases':cases},indent=2)+'\n',encoding='utf-8')
    print(f'{len(cases)} synthetic x86 reference cases passed; no differential comparison yet')

if __name__=='__main__': main()
