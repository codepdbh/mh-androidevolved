"""Find and lift one small straight-line .text candidate, offline and read-only."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from inspect_entrypoint import GAME, PCRECOMP, EXPECTED, REVISION

def main():
    if sys.argv[1:] not in ([], ['--x87']): raise SystemExit('unsupported arguments')
    require_x87 = sys.argv[1:] == ['--x87']
    if (PCRECOMP/'REVISION.txt').read_text(encoding='ascii').strip() != REVISION:
        raise SystemExit('unexpected PCRecomp revision')
    data = GAME.read_bytes()
    if hashlib.sha256(data).hexdigest() != EXPECTED:
        raise SystemExit('unexpected executable hash')
    for folder in ('pe', 'disasm', 'lift'):
        sys.path.insert(0, str(PCRECOMP/'tools'/folder))
    from pe_analyze import analyze_pe, build_iat_map
    from disasm32 import Disassembler
    from lift32 import Lifter
    info = analyze_pe(str(GAME))
    iat = build_iat_map(info)
    section = next(s for s in info.sections if s.name == '.text')
    dis = Disassembler(data, info.image_base, info.sections)
    # Scan .text for plausible prologues; these are hypotheses, not boundaries.
    section_data = data[section.raw_offset:section.raw_offset + section.raw_size]
    offset = 0
    while True:
        positions = [p for pattern in (b'\x55\x8b\xec', b'\x55\x89\xe5', b'\x53\x56\x57')
                     if (p := section_data.find(pattern, offset)) >= 0]
        if not positions: raise SystemExit('no simple candidate found in bounded scan')
        offset = min(positions)
        start = info.image_base + section.virtual_address + offset
        offset += 1
        insns = []
        calls = []
        unsuitable = False
        for ins in dis.disassemble_at(start, max_bytes=256):
            insns.append(ins)
            if ins.mnemonic in ('rdtsc', 'rdtscp', 'cpuid', 'int', 'syscall', 'sysenter', 'in', 'out'):
                unsuitable = True
                break
            if ins.is_jump or ins.mnemonic in ('int3', 'ud2', 'hlt'):
                break
            if ins.is_call: calls.append(ins.address)
            if ins.is_ret:
                break
        if len(insns) < 3 or calls or unsuitable:
            continue
        function = dis.disassemble_function(start, iat)
        if not function:
            continue
        insns = [i for block in function.blocks.values() for i in block.instructions]
        forbidden = {'rdtsc', 'rdtscp', 'cpuid', 'int', 'syscall', 'sysenter', 'in', 'out', 'int3', 'ud2', 'hlt'}
        if len(insns) < 3 or len(insns) > 100 or not any(i.is_ret for i in insns):
            continue
        if any(i.is_call or i.mnemonic in forbidden for i in insns):
            continue
        if any(i.mnemonic.startswith('f') for i in insns) != require_x87:
            continue
        code = Lifter(iat_map=iat).lift_function(function)
        out = ROOT/'private'/'analysis'/('candidate_x87' if require_x87 else 'candidate_deterministic')
        out.mkdir(parents=True, exist_ok=True)
        (out/'candidate.c').write_text(code+'\n', encoding='utf-8')
        report = {'pcrecomp_revision': REVISION, 'input_sha256': EXPECTED,
                  'address': hex(start), 'instruction_count':len(insns),
                  'imports':[], 'source_sha256':hashlib.sha256(code.encode('utf-8')).hexdigest(),
                  'todo_markers':code.count('RECOMP_TODO'),
                  'limitations':['heuristic start; not proven reachable or gameplay', 'not compiled or tested', 'calls and runtime unresolved']}
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(f'candidate={start:#x}; instructions={len(insns)}; no calls; x87={require_x87}; C written privately')
        return

if __name__ == '__main__': main()
