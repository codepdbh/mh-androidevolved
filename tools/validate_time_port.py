"""One bounded validation session; every child process uses worksafe.

Waits for memory within the existing profiles, never lowers their limits or
starts a background service. A non-memory failure stops the session at once.
"""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import worksafe

def main():
    if sys.argv[1:]:raise SystemExit('no arguments supported')
    deadline=time.monotonic()+300
    steps=[('x86-reference',worksafe.probe_time_candidate_x86),
           ('host-comparison',worksafe.compare_time_indirect_zero),
           ('arm64-build',worksafe.build_time_candidate_arm64_test),
           ('s25-comparison',worksafe.run_time_candidate_on_s25)]
    report={'status':'running','completed':[]};out=ROOT/'logs/time-validation-session.json';out.parent.mkdir(exist_ok=True)
    def save():out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    save()
    for name,action in steps:
        while True:
            if time.monotonic()>=deadline:
                report.update(status='incomplete',pending=name,reason='bounded session deadline reached');save()
                print('INCOMPLETE:',name,'deadline reached',flush=True);return 2
            free=worksafe.available_memory_mb()
            if free<1536:
                print('WAIT:',name,'RAM',free,'MiB; profiles require 1536',flush=True)
                time.sleep(min(15,max(0,deadline-time.monotonic())));continue
            print('START:',name,flush=True)
            try:result=action()
            except worksafe.WorkSafeError as exc:
                if 'insufficient' in str(exc).lower() or 'memory pressure' in str(exc).lower():
                    print('WAIT:',name,str(exc),flush=True);time.sleep(min(15,max(0,deadline-time.monotonic())));continue
                report.update(status='failed',pending=name,reason=str(exc));save();raise
            if name=='arm64-build' and (not result.get('manifest') or result['build']['returncode']!=0):
                report.update(status='failed',pending=name,reason='ARM64 build did not complete');save();return 1
            if name=='s25-comparison' and not result.get('passed'):
                report.update(status='failed',pending=name,reason='device comparisons did not pass');save();return 1
            report['completed'].append({'step':name,'result':result});save()
            print('PASS:',name,flush=True);break
    report['status']='passed';save();print('PASS: all bounded time validation steps',flush=True);return 0

if __name__=='__main__':raise SystemExit(main())
