"""Adapt exactly three verified loads in one local PCRecomp candidate."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'private/analysis/candidate_x87'
EXPECTED_SOURCE='5a40e3e13cb1c2c27ab13430dea036800cf50f7a4d3954d406eba9f6dc1556e2'
replacements={
    '*(float*)&MEM32(esp + 0x14)':'MEMF(esp + 0x14)',
    '*(float*)ADDR(edi + esi * 8)':'MEMF(edi + esi * 8)',
    '*(float*)ADDR(edx + esi * 8)':'MEMF(edx + esi * 8)',
}

def main():
    report=json.loads((BASE/'report.json').read_text(encoding='utf-8'))
    source=(BASE/'candidate.c').read_text(encoding='utf-8').removesuffix('\n')
    digest=hashlib.sha256(source.encode('utf-8')).hexdigest()
    if report['address']!='0x409960' or digest!=EXPECTED_SOURCE or report['source_sha256']!=digest:
        raise SystemExit('candidate does not match the audited translation')
    adapted=source
    for old,new in replacements.items():
        if adapted.count(old)!=1: raise SystemExit('unexpected memory expression: '+old)
        adapted=adapted.replace(old,new)
    if 'ADDR(' in adapted or '*(float*)' in adapted:
        raise SystemExit('unchecked float access remains')
    (BASE/'candidate_checked.c').write_text(adapted+'\n',encoding='utf-8')
    (BASE/'checked_report.json').write_text(json.dumps({'original_sha256':digest,
        'adapted_sha256':hashlib.sha256(adapted.encode('utf-8')).hexdigest(),
        'replacements':len(replacements),'limitations':['only this candidate', 'not behaviorally verified', 'no full PCRecomp memory integration']},indent=2)+'\n',encoding='utf-8')
    print('3 audited float loads redirected to checked access; behavioral equivalence unverified')

if __name__=='__main__': main()
