"""Compare synthetic input paths only; no input devices are used."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];base=ROOT/'private/analysis/candidate_input'
ref=json.loads((base/'x86_reference.json').read_text(encoding='utf-8'));report=json.loads((base/'report.json').read_text(encoding='utf-8'))
if ref['input_sha256']!=report['input_sha256'] or ref['candidate_source_sha256']!=report['source_sha256']:raise SystemExit('provenance mismatch')
actual=[json.loads(x) for x in (ROOT/'logs/input-mock-runtime.stdout.log').read_text(encoding='utf-8').splitlines()]
if len(actual)!=len(ref['cases']):raise SystemExit('case count mismatch')
for i,(want,got) in enumerate(zip(ref['cases'],actual)):
    for key in ('scenario','stack_hex','config_hex'):
        if want[key]!=got[key]:raise SystemExit(f'case {i}: {key} differs')
    for name in ('eax','ebx','ecx','edx','esi','edi','ebp','esp'):
        if want['registers'][name]!=got['registers'][name]:raise SystemExit(f'case {i}: {name} differs')
    if (want['registers']['eflags']&0x8d5)!=(got['registers']['eflags']&0x8d5):raise SystemExit(f'case {i}: arithmetic flags differ')
(base/'mock_comparison_report.json').write_text(json.dumps({'cases':len(actual),'registers_flags_stack_and_config':'match','scope':'synthetic input doubles; no device capture or ARM64 execution'},indent=2)+'\n',encoding='utf-8')
print(f'{len(actual)} input mock cases match on registers, arithmetic flags, stack and config')
