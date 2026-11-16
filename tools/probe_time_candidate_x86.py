"""Isolated x86 candidate slice with bounded synthetic dependencies only."""
import hashlib,json,struct,sys
import pefile
from unicorn import Uc,UcError,UC_ARCH_X86,UC_MODE_32,UC_HOOK_MEM_INVALID,UC_ERR_READ_UNMAPPED,UC_ERR_FETCH_UNMAPPED
from unicorn.x86_const import UC_X86_REG_EAX,UC_X86_REG_EBX,UC_X86_REG_ECX,UC_X86_REG_EDX,UC_X86_REG_ESI,UC_X86_REG_EDI,UC_X86_REG_EBP,UC_X86_REG_ESP,UC_X86_REG_EIP,UC_X86_REG_EFLAGS,UC_X86_REG_FPSW
from inspect_entrypoint import ROOT,GAME,EXPECTED

COPY_OBJECTS=((0,0,0,0,0,0),(0x8a2001,7,0,0,1,0),(0,0,0x8a2402,0x23,0,1),(0x8a2000,0x40,0x8a2403,0x31,1,1))
X87_INPUTS=((0x3fc00000,0x40400000,640,0x3f000000,2),(0x3fc00000,0x40400000,0,0,1),(0xbe800000,0x40e00000,0xfffffffd,0x3dcccccd,2),(0x7f800000,0x7f800000,1,0x3f800000,0))
REGS={'eax':UC_X86_REG_EAX,'ebx':UC_X86_REG_EBX,'ecx':UC_X86_REG_ECX,'edx':UC_X86_REG_EDX,
      'esi':UC_X86_REG_ESI,'edi':UC_X86_REG_EDI,'ebp':UC_X86_REG_EBP,'esp':UC_X86_REG_ESP,'eflags':UC_X86_REG_EFLAGS}
def main():
    if sys.argv[1:] not in ([],['--null-object'],['--missing-timer'],['--missing-virtual'],['--null-virtual-object']):raise SystemExit('unexpected arguments')
    null_object=sys.argv[1:]==['--null-object'];missing_timer=sys.argv[1:]==['--missing-timer']
    missing_virtual=sys.argv[1:]==['--missing-virtual'];null_virtual=sys.argv[1:]==['--null-virtual-object'];fault_case=null_object or missing_timer or missing_virtual or null_virtual
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise SystemExit('unexpected input hash')
    base=ROOT/'private/analysis/candidate_time';report=json.loads((base/'report.json').read_text())
    if report['address']!='0x6081a0':raise SystemExit('unexpected candidate')
    branch_report=json.loads((base/'dependencies/branch_report.json').read_text())
    if branch_report['address']!='0x5daa20' or branch_report['input_sha256']!=EXPECTED:raise SystemExit('unexpected dispatcher report')
    memcpy_report=json.loads((base/'dependencies/memcpy_report.json').read_text())
    if [x['address'] for x in memcpy_report['items']]!=['0x481340','0x611640'] or memcpy_report['input_sha256']!=EXPECTED:raise SystemExit('unexpected buffer copy report')
    x87_report=json.loads((base/'dependencies/x87_report.json').read_text())
    if [x['address'] for x in x87_report['items']]!=['0x5daa50','0x5ea2b0'] or x87_report['input_sha256']!=EXPECTED:raise SystemExit('unexpected x87 report')
    probe_report=json.loads((base/'dependencies/stack_probe_report.json').read_text())
    if probe_report['address']!='0x648540' or probe_report['input_sha256']!=EXPECTED:raise SystemExit('unexpected stack probe report')
    wrapper_report=json.loads((base/'dependencies/free_wrapper_report.json').read_text())
    if wrapper_report['address']!='0x401030' or wrapper_report['input_sha256']!=EXPECTED:raise SystemExit('unexpected wrapper report')
    pe=pefile.PE(data=data,fast_load=True);page=pe.get_data(0x608000-pe.OPTIONAL_HEADER.ImageBase,0x1000)
    if len(page)!=0x1000:raise SystemExit('incomplete candidate page')
    cases=[]
    specs=[(0,1 if missing_virtual or null_virtual else 0,0,0,0)] if fault_case else [(tick,result,guard,alignment,mode) for tick in (0,1234,0xffffffd0,0xffffffff) for result,guard in ((0,0),(2,0),(1,1),(1,0)) for alignment in range(4) for mode in range(4)]
    for tick,result,guard,alignment,mode in specs:
        cpu=Uc(UC_ARCH_X86,UC_MODE_32);cpu.mem_map(0x400000,0x500000);cpu.mem_write(0x608000,page)
        # Real dependencies are hash-checked against their lift reports; the rest are test doubles.
        for region in probe_report['regions']:
            address=int(region['address'],16);code=pe.get_data(address-pe.OPTIONAL_HEADER.ImageBase,region['length'])
            if hashlib.sha256(code).hexdigest()!=region['bytes_sha256']:raise SystemExit('stack probe bytes differ')
            cpu.mem_write(address,code)
        cpu.mem_write(0x605750,b'\xb8'+struct.pack('<I',result)+b'\xc2\x3c\x00')
        for address,expected in ((0x426ef0,bytes.fromhex('c3')),(0x608410,bytes.fromhex('c20400')),(0x481330,bytes.fromhex('8b442404a360c87100c3'))):
            actual=pe.get_data(address-pe.OPTIONAL_HEADER.ImageBase,len(expected))
            if actual!=expected:raise SystemExit('tiny dependency bytes differ')
            cpu.mem_write(address,actual)
        copy_code=pe.get_data(0x604d20-pe.OPTIONAL_HEADER.ImageBase,0x80)
        if len(copy_code)!=0x80:raise SystemExit('incomplete copy dependency')
        cpu.mem_write(0x604d20,copy_code)
        indirect_code=pe.get_data(0x604dc0-pe.OPTIONAL_HEADER.ImageBase,0x90)
        if len(indirect_code)!=0x90:raise SystemExit('incomplete indirect dependency')
        cpu.mem_write(0x604dc0,indirect_code)
        wrapper=pe.get_data(0x401030-pe.OPTIONAL_HEADER.ImageBase,15)
        if hashlib.sha256(wrapper).hexdigest()!=wrapper_report['bytes_sha256']:raise SystemExit('wrapper bytes differ')
        cpu.mem_write(0x401030,wrapper);cpu.mem_write(0x401b00,b'\xc2\x04\x00')
        for address in (0x493230,0x4932f0,0x800200,0x800210):cpu.mem_write(address,b'\xc3')
        setter=pe.get_data(0x604f30-pe.OPTIONAL_HEADER.ImageBase,10)
        if setter!=bytes.fromhex('8b442404894108c20400'):raise SystemExit('setter bytes differ')
        cpu.mem_write(0x604f30,setter)
        # Real buffer copy (0x481340, 0x611640) and x87 (0x5daa50, 0x5ea2b0) dependencies, checked against their lift reports.
        for item in memcpy_report['items']+x87_report['items']:
            address=int(item['address'],16);code=pe.get_data(address-pe.OPTIONAL_HEADER.ImageBase,item['bytes_length'])
            if hashlib.sha256(code).hexdigest()!=item['bytes_sha256']:raise SystemExit('buffer copy bytes differ')
            cpu.mem_write(address,code)
        # Real mode dispatcher 0x5daa20, checked against the lift report; its two callees are counters.
        dispatcher=pe.get_data(0x5daa20-pe.OPTIONAL_HEADER.ImageBase,0x21)
        if hashlib.sha256(dispatcher).hexdigest()!=branch_report['bytes_sha256']:raise SystemExit('dispatcher bytes differ')
        cpu.mem_write(0x5daa20,dispatcher)
        cpu.mem_write(0x476a80,b'\x83\x05\x00\x00\x8a\x00\x01\xc3')              # add dword [0x8a0000],1; ret
        cpu.mem_write(0x476aa0,b'\x81\x05\x00\x00\x8a\x00\x00\x01\x00\x00\xc3')  # add dword [0x8a0000],0x100; ret
        # Callees of 0x5daa50: push [esp+4]; pop [0x8a0004]; add [0x8a0008],1; ret  /  add [0x8a000c],1; ret
        cpu.mem_write(0x5db0d0,b'\xff\x74\x24\x04\x8f\x05\x04\x00\x8a\x00\x83\x05\x08\x00\x8a\x00\x01\xc3')
        cpu.mem_write(0x482f20,b'\x83\x05\x0c\x00\x8a\x00\x01\xc3')
        cpu.mem_write(0x800100,b'\xa1\x00\x00\x81\x00\x8d\x50\x28\x89\x15\x00\x00\x81\x00\xc3')
        cpu.mem_write(0x81b4fc,struct.pack('<I',0 if missing_timer else 0x800100));cpu.mem_write(0x810000,struct.pack('<I',tick))
        cpu.mem_write(0x736db8,struct.pack('<I',0 if null_virtual else 0x820000));cpu.mem_write(0x82000c,struct.pack('<I',0x821000))
        cpu.mem_write(0x821000,struct.pack('<I',0x822000));cpu.mem_write(0x822028,struct.pack('<I',0 if missing_virtual else 0x800200));cpu.mem_write(0x822024,struct.pack('<I',0x800210))
        cpu.mem_write(0x725a54,struct.pack('<I',0x860000 if mode&1 else 0));cpu.mem_write(0x725a4c,struct.pack('<I',0x860100 if mode&2 else 0))
        cpu.mem_write(0x880000+alignment,struct.pack('<I',0x8f0000));cpu.mem_write(0x8711a8,struct.pack('<I',0));cpu.mem_write(0x8711c4,struct.pack('<I',guard))
        cpu.mem_write(0x7e6ba0,bytes((i*7+3)&255 for i in range(0x400)))
        cpu.mem_write(0x7d6af0,bytes((i*5+11)&255 for i in range(0x60)))
        cpu.mem_write(0x7d6b18,struct.pack('<I',(0,1,2,0xe2df6fd3)[alignment]));cpu.mem_write(0x8a0000,struct.pack('<I',0))
        # Same synthetic objects as the C harness, selected by tick index: none, A, B, both.
        a_dst,a_size,b_dst,b_size,has_a,has_b=COPY_OBJECTS[(0,1234,0xffffffd0,0xffffffff).index(tick)]
        cpu.mem_write(0x71a860,bytes((i*3+1)&255 for i in range(0x100)))
        cpu.mem_write(0x71c87c,struct.pack('<I',0x8a1000 if has_a else 0));cpu.mem_write(0x71c880,struct.pack('<I',0x8a1400 if has_b else 0))
        for address,value in ((0x8a1170,a_dst),(0x8a11b8,a_size),(0x8a1570,b_dst),(0x8a15b8,b_size)):cpu.mem_write(address,struct.pack('<I',value))
        # Same x87 inputs as the C harness, selected by mode.
        for address,value in zip((0x7c8a78,0x7c95a0,0x7c8a74,0x7c908c,0x7d34f8),X87_INPUTS[mode]):cpu.mem_write(address,struct.pack('<I',value))
        for name,value in [('eax',0x11111111),('ebx',0x22222222),('ecx',0 if null_object else 0x870000),('edx',0x33333333),
                           ('esi',0x44444444),('edi',0x55555555),('ebp',0x66666666),('esp',0x880000+alignment),('eflags',2)]:cpu.reg_write(REGS[name],value)
        faults=[]
        if fault_case:cpu.hook_add(UC_HOOK_MEM_INVALID,lambda uc,access,address,size,value,user: faults.append((address,size)) or False)
        try:cpu.emu_start(0x6081a0,0x8f0000,timeout=500000,count=12000)
        except UcError as exc:
            expected=(UC_ERR_READ_UNMAPPED,0x11a8,4) if null_object else ((UC_ERR_READ_UNMAPPED,0xc,4) if null_virtual else (UC_ERR_FETCH_UNMAPPED,0,1))
            if not fault_case or exc.errno!=expected[0] or not faults or faults[0][0]!=expected[1] or ((null_object or null_virtual) and faults[0][1]!=expected[2]):raise
            name='null-object' if null_object else ('null-virtual-object' if null_virtual else ('missing-virtual' if missing_virtual else 'missing-timer'))
            (base/('x86_'+name+'_fault.json')).write_text(json.dumps({'input_sha256':EXPECTED,'candidate_source_sha256':report['source_sha256'],'fault_address':hex(expected[1]),'scope':'isolated synthetic fault case'},indent=2)+'\n',encoding='utf-8')
            print(name,'caused expected unmapped guest access at',hex(expected[1]));return
        if fault_case:raise SystemExit('expected guest fault not observed')
        if cpu.reg_read(UC_X86_REG_EIP)!=0x8f0000:raise RuntimeError('candidate did not return')
        cases.append({'tick':tick,'result':result,'guard':guard,'alignment':alignment,'mode':mode,'registers':{name:cpu.reg_read(reg) for name,reg in REGS.items()},
                      'stack_hex':bytes(cpu.mem_read(0x87ed00,0x1308)).hex(),
                      'object_hex':bytes(cpu.mem_read(0x870000,16)).hex(),'copy_hex':bytes(cpu.mem_read(0x71a460,0x400)).hex(),
                      'global_value':struct.unpack('<I',cpu.mem_read(0x7e8fa0,4))[0],
                      'small_dep_value':struct.unpack('<I',cpu.mem_read(0x71c860,4))[0],
                      'inner_dep_value':struct.unpack('<I',cpu.mem_read(0x7d7bdc,4))[0],
                      'global_a_after':struct.unpack('<I',cpu.mem_read(0x725a54,4))[0],'global_b_after':struct.unpack('<I',cpu.mem_read(0x725a4c,4))[0],
                      'structure_hex':bytes(cpu.mem_read(0x7d6ae4,0x10ec)).hex(),
                      'tick_after':struct.unpack('<I',cpu.mem_read(0x810000,4))[0],
                      'branch_calls':struct.unpack('<I',cpu.mem_read(0x8a0000,4))[0],
                      'copy_out_hex':bytes(cpu.mem_read(0x8a2000,0x500)).hex(),
                      'float_a':struct.unpack('<I',cpu.mem_read(0x7d3510,4))[0],'float_b':struct.unpack('<I',cpu.mem_read(0x7c8fec,4))[0],
                      'x87_arg':struct.unpack('<I',cpu.mem_read(0x8a0004,4))[0],'x87_calls':struct.unpack('<I',cpu.mem_read(0x8a0008,4))[0],
                      'x87_tail_calls':struct.unpack('<I',cpu.mem_read(0x8a000c,4))[0],
                      'fp_top':(cpu.reg_read(UC_X86_REG_FPSW)>>11)&7})
    (base/'x86_short_reference.json').write_text(json.dumps({'input_sha256':EXPECTED,'candidate_source_sha256':report['source_sha256'],
        'scope':'isolated candidate, thirteen actual dependencies, others synthetic; no game launch','cases':cases},indent=2)+'\n',encoding='utf-8')
    print(len(cases),'isolated x86 reference cases recorded')
if __name__=='__main__':main()
