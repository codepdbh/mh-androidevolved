"""Check ARM64 ELF relocatable symbols without loading the object."""
import json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'private/analysis/candidate_graphics'
def main():
    if sys.argv[1:] not in ([],['--checked'],['--precise'],['--input'],['--input-precise'],['--time'],['--time-checked'],['--time-linked'],['--time-copy-linked'],['--time-indirect'],['--time-all']): raise SystemExit('invalid arguments')
    time_all=sys.argv[1:]==['--time-all'];time_indirect=sys.argv[1:]==['--time-indirect'];time_copy=sys.argv[1:]==['--time-copy-linked'];time_linked=sys.argv[1:]==['--time-linked'];time_checked=sys.argv[1:]==['--time-checked'];time_candidate=sys.argv[1:] in (['--time'],['--time-checked'],['--time-linked'],['--time-copy-linked'],['--time-indirect'],['--time-all'])
    checked=sys.argv[1:]==['--checked'];precise=sys.argv[1:]==['--precise'];input_precise=sys.argv[1:]==['--input-precise'];input_candidate=sys.argv[1:] in (['--input'],['--input-precise'])
    base=(ROOT/'private/analysis/candidate_time/dependencies' if time_indirect else ROOT/'private/analysis/candidate_time') if time_candidate else (ROOT/'private/analysis/candidate_input' if input_candidate else BASE)
    name=('time-all-arm64.o' if time_all else ('indirect-checked-arm64.o' if time_indirect else ('time-copy-linked-arm64.o' if time_copy else ('time-linked-arm64.o' if time_linked else ('time-checked-arm64.o' if time_checked else 'candidate-arm64.o'))))) if time_candidate else (('input-precise-arm64.o' if input_precise else 'input-with-thunk-arm64.o') if input_candidate else ('graphics-precise-arm64.o' if precise else ('graphics-checked-arm64.o' if checked else 'graphics-with-thunk-arm64.o')))
    data=(base/name).read_bytes()
    if data[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',data,18)[0]!=183:
        raise SystemExit('expected little-endian ELF64 AArch64')
    shoff=struct.unpack_from('<Q',data,40)[0];entsize,num=struct.unpack_from('<HH',data,58)
    sections=[struct.unpack_from('<IIQQQQIIQQ',data,shoff+i*entsize) for i in range(num)]
    defined=set();undefined=set()
    for s in sections:
        if s[1]!=2:continue
        offset,size,link,entry=s[4],s[5],s[6],s[9]
        if not entry or link>=len(sections):raise SystemExit('invalid symbol table')
        strings=sections[link];st=data[strings[4]:strings[4]+strings[5]]
        for off in range(offset,offset+size,entry):
            name,info,other,index,value,length=struct.unpack_from('<IBBHQQ',data,off)
            if not name or name>=len(st):continue
            end=st.find(b'\0',name)
            if end<0:raise SystemExit('invalid symbol name')
            symbol=st[name:end].decode('utf-8','replace')
            if index==0:undefined.add(symbol)
            else:defined.add(symbol)
    expected=({'sub_006081A0','sub_00426EF0','sub_00481330','sub_00608410','sub_00604D20','sub_00604F30','sub_00604DC0'} if time_all else ({'sub_00604DC0'} if time_indirect else ({'sub_006081A0','sub_00426EF0','sub_00481330','sub_00608410','sub_00604D20','sub_00604F30'} if time_copy else ({'sub_006081A0','sub_00426EF0','sub_00481330','sub_00608410'} if time_linked else {'sub_006081A0'})))) if time_candidate else ({'sub_004C1BA0','sub_00644098'} if input_candidate else {'sub_004C0830','sub_0064408C'})
    if not expected.issubset(defined) or expected & undefined:raise SystemExit('candidate or thunk unresolved')
    report={'architecture':'AArch64','format':'ELF64 relocatable',
            'defined_candidates':sorted(expected),'undefined_symbols':sorted(undefined),
            'limitations':['not a shared library or APK','runtime and platform implementations unresolved','not executed']}
    (base/(('all_object_report.json' if time_all else ('indirect_object_report.json' if time_indirect else ('copy_linked_object_report.json' if time_copy else ('linked_object_report.json' if time_linked else ('checked_object_report.json' if time_checked else 'object_report.json'))))) if time_candidate else ('precise_link_report.json' if precise or input_precise else ('checked_link_report.json' if checked else 'link_report.json')))).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(f'{len(expected)} candidate symbols defined in relocatable object; {len(undefined)} external symbols remain')
if __name__=='__main__':main()
