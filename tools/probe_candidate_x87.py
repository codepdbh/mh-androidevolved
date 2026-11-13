"""Isolated x87 candidate reference with synthetic finite float inputs."""
import hashlib,json,struct,sys
from pathlib import Path
import pefile
import probe_candidate_x86 as q
from inspect_entrypoint import ROOT,GAME,EXPECTED

def bits(x): return struct.unpack('<I',struct.pack('<f',x))[0]
def main():
    if sys.argv[1:] not in ([],['--special']): raise SystemExit('unsupported arguments')
    special=sys.argv[1:]==['--special']
    data=GAME.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED: raise SystemExit('unexpected executable hash')
    base=ROOT/'private/analysis/candidate_x87'
    report=json.loads((base/'report.json').read_text(encoding='utf-8'))
    if report['address']!='0x409960': raise SystemExit('unexpected candidate')
    q.START=0x409960;q.CODE_PAGE=0x409000
    pe=pefile.PE(data=data,fast_load=True)
    code=pe.get_data(q.CODE_PAGE-pe.OPTIONAL_HEADER.ImageBase,0x1000)
    if len(code)!=0x1000: raise SystemExit('incomplete code page')
    cases=[]
    if not special:
        fixed=((5.0,0,2),(20.0,0,2),(40.0,0,2),(20.0,2,1),(30.0,0,0))
        cases=[q.probe(code,bits(key),start,end,0,0,True) for key,start,end in fixed]
        if tuple(c['result'] for c in cases)!=(0,1,3,3,2): raise SystemExit('unexpected x87 reference output')
    keybits=(0x80000000,0x7f800000,0xff800000,0x7fc00000) if special else tuple(map(bits,(0.0,5.0,10.0,15.0,20.0,25.0,30.0,35.0,-1.0)))
    cases.extend(q.probe(code,key,start,end,mode,skew,True)
        for skew in (0,1,2,3) for mode in (0,1) for key in keybits
        for start in (0,1,2) for end in (0,1,2))
    out={'scope':'isolated Unicorn x86 reference, synthetic float inputs', 'input_sha256':EXPECTED,
         'candidate_address':report['address'],'candidate_source_sha256':report['source_sha256'],'cases':cases}
    (base/('x86_special_reference.json' if special else 'x86_reference.json')).write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
    print(f'{len(cases)} {"special" if special else "finite"}-float x87 reference cases recorded')
if __name__=='__main__': main()
