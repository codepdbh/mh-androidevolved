"""Compare allocator harness output (Windows x64 or ARM64) with the Unicorn x86 reference."""
import json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if len(sys.argv)!=3 or not re.fullmatch(r'[a-z0-9-]{1,32}',sys.argv[2]):raise SystemExit('usage: compare_allocator.py <output.jsonl> <platform>')
reference=json.loads((ROOT/'private/analysis/allocator/x86_reference.json').read_text(encoding='utf-8'))
actual=[json.loads(line) for line in Path(sys.argv[1]).read_text(encoding='utf-8').splitlines() if line.strip()]
if len(actual)!=len(reference['cases']):raise SystemExit(f'case count mismatch: {len(actual)}')
for i,(want,got) in enumerate(zip(reference['cases'],actual)):
    for field in ('case','pool_hex','stack_hex','arena_fnv','malloc_request'):
        if want[field]!=got[field]:raise SystemExit(f'case {i}: {field} differs')
    for op,(a,b) in enumerate(zip(want['results'],got['results'])):
        if a!=b:raise SystemExit(f'case {i}: operation {op} result differs ({a:#x} vs {b:#x})')
    for reg in ('eax','ebx','ecx','edx','esi','edi','ebp','esp'):
        if want['registers'][reg]!=got['registers'][reg]:raise SystemExit(f'case {i}: {reg} differs')
    # With zero-fill enabled, a successful allocation ends with flags from `imul` in 0x401580:
    # Intel defines only CF/OF after IMUL (SF, ZF, AF, PF are undefined), so only those are compared.
    zero_fill=(want['case']//4)%2==1;last=want['results'][-1]
    mask=0x801 if zero_fill and last and last>>28!=0xF else 0x8d5
    if (want['registers']['eflags']&mask)!=(got['registers']['eflags']&mask):raise SystemExit(f'case {i}: defined arithmetic flags differ')
ops=sum(len(c['results']) for c in actual)
(ROOT/f'private/analysis/allocator/comparison_{sys.argv[2]}.json').write_text(json.dumps({'cases':len(actual),'operations':ops,
    'compared':['every allocate/free result','pool object (0x1268 bytes)','stack','arena FNV-1a hash','registers','six flags, or CF/OF only where IMUL leaves the others undefined'],
    'limitations':['CRT malloc double','single-threaded','not whole game']},indent=2)+'\n',encoding='utf-8')
print(len(actual),'allocator cases and',ops,'operations match the x86 reference on',sys.argv[2])
