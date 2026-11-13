"""Compare only the test-double graphics path with its isolated x86 oracle."""
import json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];base=ROOT/'private/analysis/candidate_graphics'
if sys.argv[1:] not in ([],['--precise'],['--precise-modes'],['--precise-multi']):raise SystemExit('invalid arguments')
modes=sys.argv[1:]==['--precise-modes'];multi=sys.argv[1:]==['--precise-multi'];precise=bool(sys.argv[1:])
ref=json.loads((base/('x86_multi_reference.json' if multi else ('x86_modes_reference.json' if modes else 'x86_reference.json'))).read_text(encoding='utf-8'))
report=json.loads((base/'report.json').read_text(encoding='utf-8'))
if ref['input_sha256']!=report['input_sha256'] or ref['candidate_source_sha256']!=report['source_sha256']:raise SystemExit('provenance mismatch')
actual=[json.loads(x) for x in (ROOT/'logs'/('graphics-precise-multi-runtime.stdout.log' if multi else ('graphics-precise-modes-runtime.stdout.log' if modes else ('graphics-precise-runtime.stdout.log' if precise else 'graphics-mock-runtime.stdout.log')))).read_text(encoding='utf-8').splitlines()]
if len(actual)!=len(ref['cases']):raise SystemExit('case count mismatch')
divergences=[]
for i,(want,got) in enumerate(zip(ref['cases'],actual)):
    if want['depth']!=got['depth']:raise SystemExit(f'case {i}: depth differs')
    if want['refresh']!=got['refresh']:raise SystemExit(f'case {i}: refresh differs')
    if multi and want['refresh2']!=got['refresh2']:raise SystemExit(f'case {i}: second refresh differs')
    x86=bytearray.fromhex(want['stack_hex']);native=bytearray.fromhex(got['stack_hex'])
    for offset,expected in ((28,0x4c0884),(32,0x4c08f0)) if not precise else ():
        real=struct.unpack_from('<I',x86,offset)[0];translated=struct.unpack_from('<I',native,offset)[0]
        if real!=expected or translated!=0xdead0000:raise SystemExit(f'case {i}: unexpected return-slot values')
        divergences.append({'case':i,'stack_address':hex(0x107fb0+offset),'x86':hex(real),'translated':hex(translated),'reason':'PCRecomp dummy return address'})
        native[offset:offset+4]=x86[offset:offset+4] # Compare the remaining bytes separately.
    if x86!=native:raise SystemExit(f'case {i}: additional stack differences')
    for name in ('eax','ebx','ecx','edx','esi','edi','ebp','esp'):
        if want['registers'][name]!=got['registers'][name]:raise SystemExit(f'case {i}: {name} differs')
    if (want['registers']['eflags']&0x8d5)!=(got['registers']['eflags']&0x8d5):raise SystemExit(f'case {i}: arithmetic flags differ')
(base/('precise_multi_comparison_report.json' if multi else ('precise_modes_comparison_report.json' if modes else ('precise_comparison_report.json' if precise else 'mock_comparison_report.json')))).write_text(json.dumps({'cases':len(actual),'registers_and_arithmetic_flags':'match','other_observed_stack_bytes':'match','known_stack_divergences':divergences,'scope':'synthetic Direct3D stubs; no actual graphics or ARM64 execution'},indent=2)+'\n',encoding='utf-8')
print(f'{len(actual)} mock cases: registers, arithmetic flags and observed stack match' if precise else f'{len(actual)} mock cases: registers and arithmetic flags match; two return-address stack slots differ in each case')
