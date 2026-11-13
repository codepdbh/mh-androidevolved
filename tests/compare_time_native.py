"""Compare an isolated, synthetic short path; no platform APIs are provided."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];base=ROOT/'private/analysis/candidate_time'
reference=json.loads((base/'x86_short_reference.json').read_text())
report=json.loads((base/'report.json').read_text())
if reference['input_sha256']!=report['input_sha256'] or reference['candidate_source_sha256']!=report['source_sha256']:
    raise SystemExit('candidate provenance mismatch')
actual=[json.loads(line) for line in (ROOT/'logs/time-native-run.stdout.log').read_text(encoding='utf-8').splitlines()]
if len(actual)!=len(reference['cases']):raise SystemExit('case count mismatch')
for i,(want,got) in enumerate(zip(reference['cases'],actual)):
    for field in ('tick','result','guard','alignment','mode','stack_hex','object_hex','copy_hex','structure_hex','global_value','small_dep_value','inner_dep_value','global_a_after','global_b_after','tick_after'):
        if want[field]!=got[field]:raise SystemExit(f'case {i}: {field} differs')
    for reg in ('eax','ebx','ecx','edx','esi','edi','ebp','esp'):
        if want['registers'][reg]!=got['registers'][reg]:raise SystemExit(f'case {i}: {reg} differs')
    if (want['registers']['eflags']&0x8d5)!=(got['registers']['eflags']&0x8d5):raise SystemExit(f'case {i}: arithmetic flags differ')
(base/'short_comparison_report.json').write_text(json.dumps({'cases':len(actual),'scope':'isolated candidate and six translated dependencies, remaining dependencies synthetic; both exits',
    'compared':['general registers','six arithmetic flags','observed stack','object prefix','copied buffer','global and timer state'],
    'limitations':['no real APIs','not exhaustive','not Android','not whole game']},indent=2)+'\n',encoding='utf-8')
print(len(actual),'synthetic cases match in observed state')
