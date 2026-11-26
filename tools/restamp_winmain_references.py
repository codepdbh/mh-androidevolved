"""Re-stamp the WinMain x86 references with a new translated unit, without re-tracing.

The references are produced by Unicorn running the original x86 code; their content does
not depend on the translation. The `unit_sha256` stamp only ties them to the unit they were
validated with. After a re-lift that only adds functions, the stamp may move to the new unit
when, and only when:
  - each reference was traced from the same verified executable;
  - each reference carries the previous unit's hash (the saved previous lift report);
  - every function of the previous unit is still translated (nothing lost).
Each re-stamped reference records `restamped_from`. The device and host comparisons that
follow (scripts/worksafe.py test_winmain) are what validate the new unit.
usage: restamp_winmain_references.py <previous winmain_report.json>
"""
import hashlib,json,sys
from pathlib import Path
from inspect_entrypoint import ROOT,GAME,EXPECTED
def main():
    if len(sys.argv)!=2:raise SystemExit(__doc__)
    base=ROOT/'private/analysis/winmain'
    old=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'));new=json.loads((base/'winmain_report.json').read_text(encoding='utf-8'))
    if hashlib.sha256(GAME.read_bytes()).hexdigest()!=EXPECTED:raise SystemExit('unexpected executable hash')
    if hashlib.sha256((base/'winmain_unit.c').read_bytes()).hexdigest()!=new['unit_sha256']:raise SystemExit('unit changed since lift')
    lost={i['address'] for i in old['items']}-{i['address'] for i in new['items']}
    if lost:raise SystemExit(f'{len(lost)} previously translated functions are missing; re-trace instead')
    paths=[base/'x86_reference.json',*sorted((base/'scenarios').glob('*/x86_reference.json'))]
    for path in paths:
        ref=json.loads(path.read_text(encoding='utf-8'))
        if ref.get('input_sha256')!=EXPECTED:raise SystemExit(f'{path}: traced from another executable')
        if ref.get('unit_sha256')!=old['unit_sha256']:raise SystemExit(f'{path}: not stamped with the previous unit')
    for path in paths:
        ref=json.loads(path.read_text(encoding='utf-8'))
        ref['restamped_from']=ref['unit_sha256'];ref['unit_sha256']=new['unit_sha256']
        path.write_text(json.dumps(ref,indent=1)+'\n',encoding='utf-8')
    print(len(paths),'references re-stamped:',old['unit_sha256'][:12],'->',new['unit_sha256'][:12],
          f'({len(old["items"])} -> {len(new["items"])} functions, none lost)')
if __name__=='__main__':main()
