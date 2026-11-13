"""Compare the isolated zero-argument virtual branch with synthetic methods."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];base=ROOT/'private/analysis/candidate_time/dependencies'
ref=json.loads((base/'x86_zero_reference.json').read_text());report=json.loads((base/'indirect_report.json').read_text())
if ref['input_sha256']!=report['input_sha256'] or ref['candidate_source_sha256']!=report['source_sha256']:raise SystemExit('provenance mismatch')
import sys
source=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'logs/time-indirect-zero-native.stdout.log';platform=sys.argv[2] if len(sys.argv)>2 else 'windows-x64'
import re
if not re.fullmatch(r'[a-z0-9-]{1,32}',platform):raise SystemExit('invalid platform label')
actual=[json.loads(x) for x in source.read_text(encoding='utf-8').splitlines()]
if len(actual)!=len(ref['cases']):raise SystemExit('case count mismatch')
for i,(want,got) in enumerate(zip(ref['cases'],actual)):
    for field in ('argument','alignment','stack_hex','object_hex','global_a','global_b'):
        if want[field]!=got[field]:raise SystemExit(f'case {i}: {field} differs')
    for reg in ('eax','ebx','ecx','edx','esi','edi','ebp','esp'):
        if want['registers'][reg]!=got['registers'][reg]:raise SystemExit(f'case {i}: {reg} differs')
    if (want['registers']['eflags']&0x8d5)!=(got['registers']['eflags']&0x8d5):raise SystemExit(f'case {i}: arithmetic flags differ')
(base/('zero_comparison_report.json' if platform=='windows-x64' else f'zero_comparison_report_{platform}.json')).write_text(json.dumps({'cases':len(actual),'scope':'isolated zero-argument branch with synthetic virtual methods',
    'compared':['general registers','arithmetic flags','observed stack','object and globals'],'platform':platform,'limitations':['not actual methods','not whole game']+([] if platform.startswith('android') else ['not Android'])},indent=2)+'\n',encoding='utf-8')
print(len(actual),'zero-argument virtual branch cases match')
