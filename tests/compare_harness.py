"""Generic field-by-field comparison of a harness JSONL output with its x86 reference.

usage: compare_harness.py <reference.json> <output.jsonl> <platform>
Every field of every case must match exactly, except `registers.eflags`, of
which only the six arithmetic flags (mask 0x8d5) are compared.
"""
import json,re,sys
from pathlib import Path
if len(sys.argv)!=4 or not re.fullmatch(r'[a-z0-9-]{1,32}',sys.argv[3]):raise SystemExit(__doc__)
reference=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))['cases']
actual=[json.loads(line) for line in Path(sys.argv[2]).read_text(encoding='utf-8').splitlines() if line.strip()]
if len(actual)!=len(reference):raise SystemExit(f'case count mismatch: {len(actual)} vs {len(reference)}')
for i,(want,got) in enumerate(zip(reference,actual)):
    if set(want)!=set(got):raise SystemExit(f'case {i}: field sets differ: {sorted(set(want)^set(got))}')
    for field in want:
        if field=='registers':
            for reg,value in want['registers'].items():
                mask=0x8d5 if reg=='eflags' else 0xffffffff
                if (value&mask)!=(got['registers'][reg]&mask):raise SystemExit(f'case {i}: {reg} differs ({value:#x} vs {got["registers"][reg]:#x})')
        elif want[field]!=got[field]:
            if isinstance(want[field],list):
                j=next(j for j,(a,b) in enumerate(zip(want[field],got[field])) if a!=b) if len(want[field])==len(got[field]) else -1
                raise SystemExit(f'case {i}: {field}[{j}] differs')
            raise SystemExit(f'case {i}: {field} differs')
print(len(actual),'cases match the x86 reference on',sys.argv[3],'('+', '.join(sorted(reference[0]))+')')
