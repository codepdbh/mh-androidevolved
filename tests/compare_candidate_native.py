"""Compare supervised native runtime output to the isolated Unicorn oracle."""
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if sys.argv[1:] not in ([], ['--checked'], ['--x87'], ['--x87-special']): raise SystemExit('invalid arguments')
special=sys.argv[1:]==['--x87-special']
is_x87=sys.argv[1:] in (['--x87'],['--x87-special'])
base=ROOT/'private/analysis'/('candidate_x87' if is_x87 else 'candidate_deterministic')
reference=json.loads((base/('x86_special_reference.json' if special else 'x86_reference.json')).read_text(encoding='utf-8'))
report=json.loads((base/'report.json').read_text(encoding='utf-8'))
if reference['input_sha256']!=report['input_sha256'] or reference['candidate_source_sha256']!=report['source_sha256']:
    raise SystemExit('reference provenance mismatch')
cases=reference['cases']
log=('pcrecomp-x87-special-runtime.stdout.log' if special else 'pcrecomp-x87-runtime.stdout.log') if is_x87 else ('pcrecomp-checked-runtime.stdout.log' if sys.argv[1:] else 'pcrecomp-native-runtime.stdout.log')
observed=[json.loads(line) for line in (ROOT/'logs'/log).read_text(encoding='utf-8').splitlines()]
if len(cases)!=len(observed): raise SystemExit(f'case count differs: {len(cases)} vs {len(observed)}')
for i,(expected,actual) in enumerate(zip(cases,observed)):
    for field in ('key','start','end','mode','skew','result','stack_hex','object_hex','array_hex'):
        if expected[field]!=actual[field]: raise SystemExit(f'case {i}: {field} differs: {expected[field]!r} vs {actual[field]!r}')
    for name in ('eax','ebx','ecx','edx','esi','edi','ebp','esp'):
        if expected['registers'][name]!=actual['registers'][name]: raise SystemExit(f'case {i}: {name} differs')
    if is_x87 and expected['fp_top']!=actual['fp_top']: raise SystemExit(f'case {i}: x87 stack depth differs')
    mask=0x8d5
    if (expected['registers']['eflags']&mask)!=(actual['registers']['eflags']&mask):
        raise SystemExit(f'case {i}: arithmetic flags differ: x86={expected["registers"]["eflags"]:#x}, runtime={actual["registers"]["eflags"]:#x}')
mode='x87 checked adapter' if is_x87 else ('checked adapter' if sys.argv[1:] else 'actual recomp32 header')
print(f'{len(cases)} cases agree with the {mode} on x64 Windows; ARM64 is untested')
