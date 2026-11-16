"""Lift the game's own heap behind 0x610be0 (the malloc that feeds the pool arena).

Imports allowed: EnterCriticalSection, LeaveCriticalSection and GlobalAlloc;
they are provided by runtime shims in the harness. The size-class table read
by 0x610730 at 0x7e9ee8 (six classes followed by the first dword of the next
data, which ends the search) is copied from the user's executable into a
private header so that harness and x86 reference start from the real values.
Output stays private.
"""
import hashlib,json,struct
import pefile
from recomp_lift import lift_closure
from inspect_entrypoint import ROOT,GAME,EXPECTED
IMPORTS={0x81b3e4,0x81b3e8,0x81b40c}  # EnterCriticalSection, LeaveCriticalSection, GlobalAlloc
TABLE,TABLE_DWORDS=0x7e9ee8,7
if __name__=='__main__':
    report=lift_closure([0x610be0],set(),IMPORTS,'heap')
    data=GAME.read_bytes();pe=pefile.PE(data=data,fast_load=True)
    values=struct.unpack(f'<{TABLE_DWORDS}I',pe.get_data(TABLE-pe.OPTIONAL_HEADER.ImageBase,4*TABLE_DWORDS))
    if list(values[:6])!=[4,0xc,0x14,0x24,0x34,0x44]:raise SystemExit('unexpected size-class table')
    out=ROOT/'private/analysis/heap'
    header=('/* Generated from the user\'s executable by tools/lift_heap.py; private. */\n'
            f'#define HEAP_TABLE 0x{TABLE:x}u\nstatic const uint32_t heap_table[{TABLE_DWORDS}]={{'+','.join(f'0x{v:x}u' for v in values)+'};\n')
    (out/'heap_data.h').write_text(header,encoding='utf-8',newline='\n')
    report['data']={'table':hex(TABLE),'dwords':TABLE_DWORDS,'sha256':hashlib.sha256(header.encode()).hexdigest()}
    (out/'heap_report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('translated',len(report['items']),'heap functions,',sum(i['instructions'] for i in report['items']),'instructions; imports',report['imports'])
    for item in report['items']:
        if item['rewrites']:print(' ',item['address'],item['rewrites'])
