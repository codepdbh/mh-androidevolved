"""Isolated graphics-candidate x86 oracle with synthetic Direct3D stubs."""
import hashlib,json,struct,sys
import pefile
from unicorn import Uc,UcError,UC_ARCH_X86,UC_MODE_32,UC_PROT_READ,UC_PROT_EXEC,UC_ERR_READ_UNMAPPED,UC_HOOK_MEM_INVALID
from unicorn.x86_const import UC_X86_REG_EAX,UC_X86_REG_EBX,UC_X86_REG_ECX,UC_X86_REG_EDX,UC_X86_REG_ESI,UC_X86_REG_EDI,UC_X86_REG_EBP,UC_X86_REG_ESP,UC_X86_REG_EIP,UC_X86_REG_EFLAGS
from inspect_entrypoint import ROOT,GAME,EXPECTED

REGS={'eax':UC_X86_REG_EAX,'ebx':UC_X86_REG_EBX,'ecx':UC_X86_REG_ECX,'edx':UC_X86_REG_EDX,'esi':UC_X86_REG_ESI,'edi':UC_X86_REG_EDI,'ebp':UC_X86_REG_EBP,'esp':UC_X86_REG_ESP,'eflags':UC_X86_REG_EFLAGS}

def main():
    if sys.argv[1:] not in ([],['--modes'],['--multi'],['--null']):raise SystemExit('invalid arguments')
    modes=sys.argv[1:]==['--modes'];multi=sys.argv[1:]==['--multi'];null_case=sys.argv[1:]==['--null']
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    base=ROOT/'private/analysis/candidate_graphics';report=json.loads((base/'report.json').read_text(encoding='utf-8'))
    if report['address']!='0x4c0830':raise SystemExit('unexpected candidate')
    pe=pefile.PE(data=data,fast_load=True);imagebase=pe.OPTIONAL_HEADER.ImageBase
    cases=[]
    specs=([(d,a,b) for d in (16,24,32) for a,b in ((30,60),(60,30),(0,60),(30,0))] if multi else
           ([(d,r,0) for d in (16,24,32) for r in (0,30,60)] if modes else ([(32,0,0)] if null_case else [(d,0,0) for d in (16,24,32)])))
    for depth,refresh,refresh2 in specs:
        cpu=Uc(UC_ARCH_X86,UC_MODE_32)
        for page in (0x100000,0x200000,0x210000,0x220000,0x300000,0x4c0000,0x644000,0x735000,0x81b000):cpu.mem_map(page,0x10000 if page==0x100000 else 0x1000)
        for page in (0x4c0000,0x644000):
            code=pe.get_data(page-imagebase,0x1000)
            if len(code)!=0x1000:raise SystemExit('incomplete code page')
            cpu.mem_write(page,code);cpu.mem_protect(page,0x1000,UC_PROT_READ|UC_PROT_EXEC)
        # These machine-code functions are test doubles, not Direct3D implementations.
        cpu.mem_write(0x300000,b'\xb8'+struct.pack('<I',0 if null_case else 0x200000)+b'\xc2\x04\x00')
        cpu.mem_write(0x300010,(b'\xb8'+struct.pack('<I',2 if multi else 1) if (modes or multi) else b'\x31\xc0')+b'\xc2\x08\x00')
        cpu.mem_write(0x300020,b'\xb8\x00\x00\x00\x00\xc2\x04\x00')
        if multi:
            # Refresh values come from a synthetic two-element guest table.
            enum=(b'\x8b\x44\x24\x10\xc7\x00'+struct.pack('<I',640)+b'\xc7\x40\x04'+struct.pack('<I',480)+
                  b'\x8b\x4c\x24\x0c\x8b\x0c\x8d'+struct.pack('<I',0x220000)+b'\x89\x48\x08'+
                  b'\xc7\x40\x0c'+struct.pack('<I',0x16)+b'\x31\xc0\xc2\x10\x00')
            cpu.mem_write(0x220000,struct.pack('<II',refresh,refresh2));cpu.mem_write(0x300030,enum)
        elif modes:
            # mov eax,[esp+16]; populate a synthetic mode; return HRESULT 0.
            enum=(b'\x8b\x44\x24\x10\xc7\x00'+struct.pack('<I',640)+b'\xc7\x40\x04'+struct.pack('<I',480)+
                  b'\xc7\x40\x08'+struct.pack('<I',refresh)+b'\xc7\x40\x0c'+struct.pack('<I',0x16)+b'\x31\xc0\xc2\x10\x00')
            cpu.mem_write(0x300030,enum)
        cpu.mem_protect(0x300000,0x1000,UC_PROT_READ|UC_PROT_EXEC)
        cpu.mem_write(0x81b52c,struct.pack('<I',0x300000));cpu.mem_write(0x200000,struct.pack('<I',0x210000))
        cpu.mem_write(0x210018,struct.pack('<I',0x300010));cpu.mem_write(0x210008,struct.pack('<I',0x300020));cpu.mem_write(0x21001c,struct.pack('<I',0x300030))
        esp=0x108000;cpu.mem_write(esp,struct.pack('<4I',0x320000,640,480,depth))
        for name,value in [('eax',0),('ebx',0x11111111),('ecx',0),('edx',0),('esi',0x22222222),('edi',0x33333333),('ebp',0x44444444),('esp',esp),('eflags',2)]:cpu.reg_write(REGS[name],value)
        invalid=[]
        if null_case: cpu.hook_add(UC_HOOK_MEM_INVALID,lambda uc,access,address,size,value,user: invalid.append((address,size)) or False)
        try: cpu.emu_start(0x4c0830,0x320000,timeout=200000,count=5000)
        except UcError as exc:
            if not null_case or exc.errno!=UC_ERR_READ_UNMAPPED or invalid!=[(0,4)]:raise
            (base/'x86_null_reference.json').write_text(json.dumps({'input_sha256':EXPECTED,'candidate_source_sha256':report['source_sha256'],'fault':'unmapped read','address':0,'size':4},indent=2)+'\n',encoding='utf-8')
            print('synthetic null creation causes an unmapped 4-byte read at guest address zero')
            return
        if null_case:raise SystemExit('expected null read fault did not occur')
        if cpu.reg_read(UC_X86_REG_EIP)!=0x320000:raise RuntimeError('candidate did not return within limits')
        cases.append({'depth':depth,'refresh':refresh,'refresh2':refresh2,'registers':{name:cpu.reg_read(reg) for name,reg in REGS.items()},'stack_hex':bytes(cpu.mem_read(esp-80,96)).hex()})
    if not modes and not multi and any(c['registers']['eax']!=0xffffffff for c in cases):raise SystemExit('unexpected zero-mode result')
    out={'scope':'isolated x86 with synthetic API and COM test doubles; no graphics', 'input_sha256':EXPECTED,
         'candidate_source_sha256':report['source_sha256'],'cases':cases}
    (base/('x86_multi_reference.json' if multi else ('x86_modes_reference.json' if modes else 'x86_reference.json'))).write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
    print(f'{len(cases)} {"two-mode" if multi else ("one-mode" if modes else "zero-mode")} reference cases recorded; no real Direct3D')
if __name__=='__main__':main()
