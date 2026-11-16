"""One bounded session: validate the translated harness on the S25, rebuild the
diagnostic APK and update it in place on the phone.

Every child process runs through worksafe profiles. Waits (up to ten minutes in
total) only for memory; any other failure stops the session. Does not launch
the app and does not start a background service.
"""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import worksafe

def main():
    if sys.argv[1:] not in ([],['--skip-validation']):raise SystemExit('usage: deploy_diagnostic_app.py [--skip-validation]')
    deadline=time.monotonic()+600
    steps=[]
    if not sys.argv[1:]:
        steps+=[('arm64-build',worksafe.build_time_candidate_arm64_test,1536),('s25-validation',worksafe.run_time_candidate_on_s25,1536)]
    steps+=[('native-library',worksafe.check_android_cmake,1536),('apk',worksafe.build_diagnostic_apk,1024),('update-on-s25',worksafe.update_diagnostic_on_s25,1024)]
    report={'status':'running','completed':{}};out=ROOT/'logs/deploy-diagnostic-session.json';out.parent.mkdir(exist_ok=True)
    def save():out.write_text(json.dumps(report,indent=2,default=str)+'\n',encoding='utf-8')
    save()
    for name,action,need in steps:
        while True:
            if time.monotonic()>=deadline:
                report.update(status='incomplete',pending=name,reason='deadline reached waiting for memory');save()
                print('INCOMPLETE:',name,flush=True);return 2
            free=worksafe.available_memory_mb()
            if free<need:
                print('WAIT:',name,'RAM',free,'MiB, needs',need,flush=True);time.sleep(min(15,max(1,deadline-time.monotonic())));continue
            print('START:',name,'RAM',free,flush=True)
            try:result=action()
            except worksafe.WorkSafeError as exc:
                text=str(exc).lower()
                if 'insufficient' in text or 'memory pressure' in text:
                    print('WAIT:',name,exc,flush=True);time.sleep(15);continue
                report.update(status='failed',pending=name,reason=str(exc));save();print('FAILED:',name,exc,flush=True);return 1
            break
        ok=True
        if name=='arm64-build':ok=bool(result.get('manifest')) and result['build']['returncode']==0
        if name=='s25-validation':ok=bool(result.get('passed'))
        if name=='native-library':ok=all(result.get(k) and result[k]['returncode']==0 and not result[k]['timed_out'] for k in ('configure','build','verify'))
        report['completed'][name]={k:v for k,v in result.items() if not isinstance(v,dict)} if isinstance(result,dict) else str(result)
        save()
        if not ok:
            report.update(status='failed',pending=name,reason='step reported failure');save();print('FAILED:',name,flush=True);return 1
        print('DONE:',name,flush=True)
    report['status']='complete';save();print('COMPLETE',flush=True);return 0

if __name__=='__main__':raise SystemExit(main())
