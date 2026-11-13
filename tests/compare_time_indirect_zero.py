"""Compare the isolated zero-argument virtual branch with synthetic methods."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];base=ROOT/'private/analysis/candidate_time/dependencies'
ref=json.loads((base/'x86_zero_reference.json').read_text());report=json.loads((base/'indirect_report.json').read_text())
if ref['input_sha256']!=report['input_sha256'] or ref['candidate_source_sha256']!=report['source_sha256']:raise SystemExit('provenance mismatch')
actual=[json.loads(x) for x in (ROOT/'logs/time-indirect-zero-native.stdout.log').read_text(encoding='utf-8').splitlines()]
if len(actual)!=len(ref['cases']):raise SystemExit('case count mismatch')
for i,(want,got) in enumerate(zip(ref['cases'],actual)):
    for field in ('argument','alignment','stack_hex','object_hex','global_a','global_b'):
        if want[field]!=got[field]:raise SystemExit(f'case {i}: {field} differs')
    for reg in ('eax','ebx','ecx','edx','esi','edi','ebp','esp'):
        if want['registers'][reg]!=got['registers'][reg]:raise SystemExit(f'case {i}: {reg} differs')
    if (want['registers']['eflags']&0x8d5)!=(got['registers']['eflags']&0x8d5):raise SystemExit(f'case {i}: arithmetic flags differ')
(base/'zero_comparison_report.json').write_text(json.dumps({'cases':len(actual),'scope':'isolated zero-argument branch with synthetic virtual methods',
    'compared':['general registers','arithmetic flags','observed stack','object and globals'],'limitations':['not actual methods','not Android','not whole game']},indent=2)+'\n',encoding='utf-8')
print(len(actual),'zero-argument virtual branch cases match')
