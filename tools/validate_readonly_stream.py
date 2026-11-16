"""Bounded foreground validation; no background service or relaxed limits."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import worksafe
def main():
    if sys.argv[1:] not in ([],['--handles'],['--handles-build']):raise SystemExit('invalid validation profile')
    handles=bool(sys.argv[1:]);build_only=sys.argv[1:]==['--handles-build']
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        free=worksafe.available_memory_mb()
        if free<1024:
            print('WAIT: real read-only test, RAM',free,'MiB',flush=True);time.sleep(10);continue
        try:result=worksafe.run_real_readonly_stream_s25(with_handles=handles,build_only=build_only)
        except worksafe.WorkSafeError as exc:
            if 'insufficient RAM' in str(exc):print('WAIT:',exc,flush=True);time.sleep(10);continue
            raise
        print(json.dumps({k:v for k,v in result.items() if k!='source_inputs'}),flush=True);return 0
    print('INCOMPLETE: read-only test did not start within memory wait budget',flush=True);return 2
if __name__=='__main__':raise SystemExit(main())
