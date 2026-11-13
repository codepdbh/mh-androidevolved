"""Bounded, read-only PCRecomp disassembly of the known local executable entry."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
PCRECOMP = ROOT/'private'/'pcrecomp'
GAME = ROOT/'Manhunt Collection'/'Manhunt'/'manhunt.exe'
EXPECTED = '5001b64f77690316330575fcfe6acd5c5115c5476c183ffec0d86779b0686b52'
REVISION = '93a74327f33d399d2bf4ee606c7a72388c193617'

def main():
    if (PCRECOMP/'REVISION.txt').read_text(encoding='ascii').strip() != REVISION:
        raise SystemExit('unexpected PCRecomp revision')
    data = GAME.read_bytes()
    if hashlib.sha256(data).hexdigest() != EXPECTED:
        raise SystemExit('executable hash changed; refusing to use prior assumptions')
    sys.path.insert(0, str(PCRECOMP/'tools'/'pe'))
    sys.path.insert(0, str(PCRECOMP/'tools'/'disasm'))
    from pe_analyze import analyze_pe
    from disasm32 import Disassembler
    info = analyze_pe(str(GAME))
    va = info.image_base + info.entry_point_rva
    dis = Disassembler(data, info.image_base, info.sections)
    # Only a 128-byte linear window. No whole-image scan or protection bypass.
    instructions = list(dis.disassemble_at(va, max_bytes=128))
    result = {'revision':REVISION, 'input_sha256':EXPECTED, 'entry_va':hex(va),
              'scope':'128-byte linear window; no control-flow or reachability guarantee',
              'instructions':[{'address':hex(i.address),'size':i.size,'mnemonic':i.mnemonic,'operands':i.op_str} for i in instructions]}
    out = ROOT/'private'/'analysis'/'entrypoint.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(f'entry={va:#x}; decoded={len(instructions)}; private output={out}')

if __name__ == '__main__': main()
