"""Compare the ARM64 slot-loader harness output with the Unicorn x86 reference."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if len(sys.argv)!=2:raise SystemExit('usage: compare_loader.py <device-output.jsonl>')
reference=json.loads((ROOT/'private/analysis/loader/x86_reference.json').read_text(encoding='utf-8'))
actual=[json.loads(line) for line in Path(sys.argv[1]).read_text(encoding='utf-8').splitlines() if line.strip()]
if len(actual)!=len(reference['cases']):raise SystemExit(f'case count mismatch: {len(actual)} vs {len(reference["cases"])}')
for i,(want,got) in enumerate(zip(reference['cases'],actual)):
    for field in ('scenario','alignment','api','stack_hex','object_hex','buffers_hex','heap_hex'):
        if want[field]!=got[field]:raise SystemExit(f'case {i}: {field} differs')
    for reg in ('eax','ebx','ecx','edx','esi','edi','ebp','esp'):
        if want['registers'][reg]!=got['registers'][reg]:raise SystemExit(f'case {i}: {reg} differs ({want["registers"][reg]:#x} vs {got["registers"][reg]:#x})')
    if (want['registers']['eflags']&0x8d5)!=(got['registers']['eflags']&0x8d5):raise SystemExit(f'case {i}: arithmetic flags differ')
results=sorted({(c['scenario'],c['registers']['eax']) for c in actual})
(ROOT/'private/analysis/loader/comparison_android-arm64.json').write_text(json.dumps({'cases':len(actual),'results_by_scenario':results,
    'compared':['general registers','six arithmetic flags','stack','object and slot markers','read buffers','heap and allocator state','API call counts'],
    'limitations':['synthetic slot files','pool allocator doubles','read-only API subset only','not whole game']},indent=2)+'\n',encoding='utf-8')
print(len(actual),'loader cases match the x86 reference; results by scenario',results)
