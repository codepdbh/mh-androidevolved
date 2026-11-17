"""Lift the refresh-rate selector 0x4c0830 (Direct3D 8 mode enumeration) for the D3D8 shim.

Its call to Direct3DCreate8 goes through the import thunk 0x64408c, verified here
to be exactly `jmp dword ptr [<Direct3DCreate8 IAT slot>]`; the harness provides
that thunk with runtime/d3d8.c. COM calls through the vtable become fail-closed
dispatches that the harness routes to the shim.
"""
import pefile
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
from recomp_lift import lift_closure
from inspect_entrypoint import GAME
THUNK=0x64408c
def main():
    pe=pefile.PE(data=GAME.read_bytes());base=pe.OPTIONAL_HEADER.ImageBase
    slot=[imp.address for e in pe.DIRECTORY_ENTRY_IMPORT for imp in e.imports if imp.name==b'Direct3DCreate8']
    if len(slot)!=1:raise SystemExit('Direct3DCreate8 import not found')
    ins=list(Cs(CS_ARCH_X86,CS_MODE_32).disasm(pe.get_data(THUNK-base,6),THUNK,count=1))
    if len(ins)!=1 or ins[0].mnemonic!='jmp' or ins[0].op_str!=f'dword ptr [{slot[0]:#x}]':raise SystemExit('unexpected import thunk')
    report=lift_closure([0x4c0830],{THUNK},set(),'graphics_d3d8',max_functions=8,indirect=True)
    print('translated',len(report['items']),'function(s),',sum(i['instructions'] for i in report['items']),'instructions;',
          sum(1 for i in report['items'] for s in i['sites'] if 'indirect' in s),'COM call sites; thunk',hex(THUNK),'->',hex(slot[0]))
if __name__=='__main__':main()
