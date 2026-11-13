import ctypes, json, sys, tempfile, unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import worksafe
CHILD=str(Path(__file__).with_name('test_child.py'))
def isolated_device_root(parent):
 source=worksafe.ROOT;root=Path(parent)/'project';(root/'config').mkdir(parents=True);(root/'build/device-tests').mkdir(parents=True)
 (root/'config/work_safe.json').write_bytes((source/'config/work_safe.json').read_bytes())
 for name in ('manifest.json','guest_memory_test','pe32_test','dispatch_manifest.json','dispatch_test'):
  path=source/'build/device-tests'/name
  if path.is_file():(root/'build/device-tests'/name).write_bytes(path.read_bytes())
 return root
class WorkSafeTests(unittest.TestCase):
 def test_normal(self):
  r=worksafe.run([sys.executable,CHILD],timeout=5,log_name='test-normal'); self.assertEqual(r['returncode'],0); self.assertFalse(r['timed_out']); self.assertGreaterEqual(r['cpu_count'],1)
  info=json.loads(Path(r['log']+'.stdout.log').read_text()); self.assertEqual(info['priority'],0x4000); self.assertEqual(info['affinity'].bit_count(),r['cpu_count'])
 def test_timeout(self):
  r=worksafe.run([sys.executable,CHILD,'sleep'],timeout=0.3,log_name='test-timeout'); self.assertTrue(r['timed_out'])
 def test_bounded_stdin(self):
  cfg=json.loads((worksafe.ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
  r=worksafe._run_job([sys.executable,CHILD,'stdin'],5,'test-stdin',cfg,max_processes=1,memory_mb=256,input_bytes=b'fixed test input')
  self.assertEqual(r['returncode'],0);self.assertEqual(Path(r['log']+'.stdout.log').read_text().strip(),'fixed test input')
  with self.assertRaises(worksafe.WorkSafeError):worksafe._run_job([],5,'bad',cfg,max_processes=1,memory_mb=256,input_bytes=b'x'*(2*1024*1024+1))
 def test_stdin_timeout_when_child_does_not_read(self):
  cfg=json.loads((worksafe.ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
  r=worksafe._run_job([sys.executable,CHILD,'sleep'],0.4,'test-stdin-timeout',cfg,max_processes=1,memory_mb=256,input_bytes=b'x'*(1024*1024))
  self.assertTrue(r['timed_out'])
 def test_reject_unapproved(self):
  with self.assertRaises(worksafe.WorkSafeError): worksafe.run(['manhunt.exe'])
  with self.assertRaises(worksafe.WorkSafeError): worksafe.run([sys.executable,'-c','print(1)'])
 def test_tree_timeout(self):
  r=worksafe.run([sys.executable,CHILD,'tree'],timeout=1,log_name='test-tree',_profile='tree_test')
  self.assertTrue(r['timed_out'])
  pid=json.loads(Path(r['log']+'.stdout.log').read_text())['child_pid']
  k=ctypes.WinDLL('kernel32',use_last_error=True); k.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]; k.OpenProcess.restype=ctypes.c_void_p
  k.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]; k.WaitForSingleObject.restype=ctypes.c_ulong
  k.CloseHandle.argtypes=[ctypes.c_void_p]
  h=k.OpenProcess(0x100000,False,pid)
  if h:
   try: self.assertEqual(k.WaitForSingleObject(h,3000),0,'child still running after job closed')
   finally: k.CloseHandle(h)
 def test_build_rejects_memory_pressure(self):
  with patch.object(worksafe,'available_memory_mb',return_value=1), patch.object(worksafe,'_run_job') as launch:
   with self.assertRaises(worksafe.WorkSafeError): worksafe.build_android()
   launch.assert_not_called()
 def test_device_runner_rejects_ambiguous_or_wrong_device(self):
  if not (worksafe.ROOT/'build/device-tests/manifest.json').is_file(): self.skipTest('device test artifacts absent')
  with tempfile.TemporaryDirectory() as temporary:
   root=isolated_device_root(temporary)
   calls=[]
   def fake(argv,seconds,name,cfg,**kwargs):
    calls.append(name);log=Path(temporary)/name
    payload={'device-list':'List of devices attached\nfirst device\nsecond device\n',
             'device-model':'Pixel 9','device-abi':'arm64-v8a'}.get(name,'')
    Path(str(log)+'.stdout.log').write_text(payload,encoding='utf-8')
    return {'returncode':0,'timed_out':False,'log':str(log)}
   with patch.object(worksafe,'ROOT',root),patch.object(worksafe,'available_memory_mb',return_value=2048),patch.object(worksafe,'_run_job',side_effect=fake):
    with self.assertRaises(worksafe.WorkSafeError):worksafe.run_android_device_tests()
    self.assertEqual(calls,['device-list'])
   calls.clear()
   def wrong(argv,seconds,name,cfg,**kwargs):
    if name=='device-list':
     calls.append(name);log=Path(temporary)/name;Path(str(log)+'.stdout.log').write_text('List of devices attached\nfirst device\n',encoding='utf-8');return {'returncode':0,'timed_out':False,'log':str(log)}
    return fake(argv,seconds,name,cfg,**kwargs)
   with patch.object(worksafe,'ROOT',root),patch.object(worksafe,'available_memory_mb',return_value=2048),patch.object(worksafe,'_run_job',side_effect=wrong):
    with self.assertRaises(worksafe.WorkSafeError):worksafe.run_android_device_tests()
    self.assertEqual(calls,['device-list','device-model','device-abi'])
 def test_device_runner_uses_unique_directory_and_exact_cleanup(self):
  manifest_path=worksafe.ROOT/'build/device-tests/manifest.json'
  if not manifest_path.is_file():self.skipTest('device test artifacts absent')
  manifest=json.loads(manifest_path.read_text(encoding='utf-8'));hashes={x['name']:x['sha256'] for x in manifest['tests']}
  with tempfile.TemporaryDirectory() as temporary:
   root=isolated_device_root(temporary)
   calls=[]
   def fake(argv,seconds,name,cfg,**kwargs):
    calls.append((name,argv));log=Path(temporary)/name
    payload={'device-list':'List of devices attached\nserial123 device\n','device-model':'SM-S931B','device-abi':'arm64-v8a,armeabi-v7a'}.get(name,'')
    if name.startswith('device-hash-'):payload=hashes[name.removeprefix('device-hash-')]+'  file'
    Path(str(log)+'.stdout.log').write_text(payload,encoding='utf-8')
    return {'returncode':0,'timed_out':False,'log':str(log)}
   with patch.object(worksafe,'ROOT',root),patch.object(worksafe,'available_memory_mb',return_value=2048),patch.object(worksafe,'_run_job',side_effect=fake),patch('secrets.token_hex',return_value='abc123'):
    result=worksafe.run_android_device_tests()
   self.assertEqual(result['tests'],{'guest_memory_test':'passed','pe32_test':'passed'})
   actions={name:argv for name,argv in calls};self.assertEqual(sum(name.startswith('device-push-') for name,_ in calls),2)
   self.assertEqual(actions['device-cleanup-files'][-3:],['-f','/data/local/tmp/mhae_abc123/guest_memory_test','/data/local/tmp/mhae_abc123/pe32_test'])
   self.assertEqual(actions['device-cleanup-dir'][-1],'/data/local/tmp/mhae_abc123')
 def test_device_runner_cleans_up_when_hash_check_fails(self):
  if not (worksafe.ROOT/'build/device-tests/manifest.json').is_file():self.skipTest('device test artifacts absent')
  with tempfile.TemporaryDirectory() as temporary:
   root=isolated_device_root(temporary)
   calls=[]
   def fake(argv,seconds,name,cfg,**kwargs):
    calls.append((name,argv));log=Path(temporary)/name
    payload={'device-list':'List of devices attached\nserial123 device\n','device-model':'SM-S931B','device-abi':'arm64-v8a',
             'device-hash-guest_memory_test':'0'*64+'  file'}.get(name,'')
    Path(str(log)+'.stdout.log').write_text(payload,encoding='utf-8')
    return {'returncode':0,'timed_out':False,'log':str(log)}
   with patch.object(worksafe,'ROOT',root),patch.object(worksafe,'available_memory_mb',return_value=2048),patch.object(worksafe,'_run_job',side_effect=fake),patch('secrets.token_hex',return_value='abc123'):
    with self.assertRaises(worksafe.WorkSafeError):worksafe.run_android_device_tests()
   actions={name:argv for name,argv in calls}
   self.assertNotIn('device-run-guest_memory_test',actions)
   self.assertEqual(actions['device-cleanup-files'][-2:],['-f','/data/local/tmp/mhae_abc123/guest_memory_test'])
   self.assertEqual(actions['device-cleanup-dir'][-1],'/data/local/tmp/mhae_abc123')
 def test_device_dispatch_runner_requires_all_expected_failures(self):
  manifest_path=worksafe.ROOT/'build/device-tests/dispatch_manifest.json'
  if not manifest_path.is_file():self.skipTest('dispatch artifact absent')
  digest=json.loads(manifest_path.read_text(encoding='utf-8'))['tests'][0]['sha256']
  with tempfile.TemporaryDirectory() as temporary:
   root=isolated_device_root(temporary)
   calls=[]
   def fake(argv,seconds,name,cfg,**kwargs):
    calls.append((name,argv));log=Path(temporary)/name
    payload={'device-list':'List of devices attached\nserial123 device\n','device-model':'SM-S938B','device-abi':'arm64-v8a',
             'device-hash-dispatch_test':digest+'  file'}.get(name,'')
    Path(str(log)+'.stdout.log').write_text(payload,encoding='utf-8')
    code=74 if name in ('device-run-missing-call','device-run-missing-tail','device-run-missing-precise') else 0
    return {'returncode':code,'timed_out':False,'log':str(log)}
   with patch.object(worksafe,'ROOT',root),patch.object(worksafe,'available_memory_mb',return_value=2048),patch.object(worksafe,'_run_job',side_effect=fake),patch('secrets.token_hex',return_value='abc123'):
    result=worksafe.run_android_device_tests(dispatch_only=True)
   self.assertEqual(result['tests'],{'dispatch_test':'passed'})
   names=[name for name,_ in calls]
   for name in ('device-run-missing-call','device-run-missing-tail','device-run-missing-precise','device-cleanup-files','device-cleanup-dir'):self.assertIn(name,names)
 def test_device_runner_records_uncertain_mkdir_without_deleting(self):
  if not (worksafe.ROOT/'build/device-tests/manifest.json').is_file():self.skipTest('device test artifacts absent')
  with tempfile.TemporaryDirectory() as temporary:
   root=isolated_device_root(temporary);calls=[]
   def fake(argv,seconds,name,cfg,**kwargs):
    calls.append(name);log=Path(temporary)/name
    payload={'device-list':'List of devices attached\nserial123 device\n','device-model':'SM-S938B','device-abi':'arm64-v8a'}.get(name,'')
    Path(str(log)+'.stdout.log').write_text(payload,encoding='utf-8')
    return {'returncode':1 if name=='device-mkdir' else 0,'timed_out':False,'log':str(log)}
   with patch.object(worksafe,'ROOT',root),patch.object(worksafe,'available_memory_mb',return_value=2048),patch.object(worksafe,'_run_job',side_effect=fake),patch('secrets.token_hex',return_value='abc123'):
    with self.assertRaises(worksafe.WorkSafeError):worksafe.run_android_device_tests()
   intent=json.loads((root/'logs/device-last-directory.json').read_text(encoding='utf-8'))
   self.assertEqual(intent,{'remote_directory':'/data/local/tmp/mhae_abc123','cleanup':'unconfirmed'})
   self.assertNotIn('device-cleanup-dir',calls)
 def test_device_runner_cleans_up_if_memory_drops(self):
  if not (worksafe.ROOT/'build/device-tests/manifest.json').is_file():self.skipTest('device test artifacts absent')
  with tempfile.TemporaryDirectory() as temporary:
   root=isolated_device_root(temporary)
   calls=[]
   def fake(argv,seconds,name,cfg,**kwargs):
    calls.append((name,argv));log=Path(temporary)/name
    payload={'device-list':'List of devices attached\nserial123 device\n','device-model':'SM-S938B','device-abi':'arm64-v8a'}.get(name,'')
    Path(str(log)+'.stdout.log').write_text(payload,encoding='utf-8')
    return {'returncode':0,'timed_out':False,'log':str(log)}
   with patch.object(worksafe,'ROOT',root),patch.object(worksafe,'available_memory_mb',side_effect=[2048]*6+[512]),patch.object(worksafe,'_run_job',side_effect=fake),patch('secrets.token_hex',return_value='abc123'):
    with self.assertRaises(worksafe.WorkSafeError):worksafe.run_android_device_tests()
   names=[name for name,_ in calls]
   self.assertNotIn('device-run-guest_memory_test',names)
   self.assertIn('device-cleanup-files',names);self.assertIn('device-cleanup-dir',names)
 def test_dispatch_single_session_validates_and_confirms_cleanup(self):
  origin=worksafe.ROOT/'build/device-tests'
  if not (origin/'dispatch_manifest.json').is_file():self.skipTest('dispatch artifact absent')
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary);(root/'config').mkdir();(root/'build/device-tests').mkdir(parents=True)
   (root/'config/work_safe.json').write_bytes((worksafe.ROOT/'config/work_safe.json').read_bytes())
   for name in ('dispatch_manifest.json','dispatch_test'):(root/'build/device-tests'/name).write_bytes((origin/name).read_bytes())
   calls=[]
   def fake(argv,seconds,name,cfg,**kwargs):
    calls.append((name,argv,kwargs));log=root/(name+'-log')
    text=('List of devices attached\nserial123 device\n' if name=='device-dispatch-list' else
          'MHAE_MODEL=SM-S938B\nMHAE_ABI=arm64-v8a\nMHAE_TESTS_PASSED\nMHAE_CLEANUP_OK\n')
    Path(str(log)+'.stdout.log').write_text(text,encoding='utf-8')
    return {'returncode':0,'timed_out':False,'log':str(log)}
   with patch.object(worksafe,'ROOT',root),patch.object(worksafe,'available_memory_mb',return_value=2048),patch.object(worksafe,'_run_job',side_effect=fake),patch('secrets.token_hex',return_value='abc123'):
    result=worksafe.run_android_dispatch_single_session()
   self.assertEqual(result['tests'],{'dispatch_test':'passed'});self.assertEqual(result['cleanup'],'confirmed')
   self.assertEqual([x[0] for x in calls],['device-dispatch-list','device-dispatch-shell-check','device-dispatch-session'])
   self.assertEqual(calls[2][1][-3:],['shell','-T','sh'])
   script=calls[2][2]['input_bytes'].decode('ascii')
   self.assertLess(script.index('MHAE_BAD_MODEL'),script.index('mkdir "$d"'))
   self.assertIn('/data/local/tmp/mhae_abc123',script);self.assertIn('sha256sum "$p"',script)
   self.assertIn('rm -f "$p" && rmdir "$d"',script);self.assertNotIn('rm -r',script)
   self.assertEqual(calls[1][2]['input_bytes'],calls[2][2]['input_bytes'])
   self.assertEqual(json.loads((root/'logs/device-dispatch-attempt.json').read_text(encoding='utf-8'))['cleanup'],'confirmed')
   shell=Path(__import__('os').environ.get('ProgramFiles',r'C:\Program Files'))/'Git'/'bin'/'sh.exe'
   if shell.is_file() and worksafe.available_memory_mb()>=1024:
    cfg=json.loads((worksafe.ROOT/'config/work_safe.json').read_text(encoding='utf-8'))
    syntax=worksafe._run_job([str(shell),'-n'],15,'test-device-shell-syntax',cfg,max_processes=2,memory_mb=256,input_bytes=script.encode('ascii'))
    self.assertEqual(syntax['returncode'],0,Path(syntax['log']+'.stderr.log').read_text(errors='replace'))
 def test_device_temp_inspection_is_read_only_and_validates_output(self):
  with tempfile.TemporaryDirectory() as temporary:
   calls=[]
   def fake(argv,seconds,name,cfg,**kwargs):
    calls.append((name,argv,kwargs));log=Path(temporary)/name
    value=('List of devices attached\nserial123 device\n' if name=='device-temp-list' else '/data/local/tmp/mhae_0123456789abcdef\n')
    Path(str(log)+'.stdout.log').write_text(value,encoding='utf-8')
    return {'returncode':0,'timed_out':False,'log':str(log)}
   with patch.object(worksafe,'available_memory_mb',return_value=2048),patch.object(worksafe,'_run_job',side_effect=fake):
    result=worksafe.inspect_android_temp_dirs()
   self.assertEqual(result,['/data/local/tmp/mhae_0123456789abcdef'])
   script=calls[1][2]['input_bytes'].decode('ascii')
   self.assertIn('find /data/local/tmp',script);self.assertNotIn('rm ',script)
 def test_dispatch_single_session_records_unconfirmed_cleanup_on_disconnect(self):
  origin=worksafe.ROOT/'build/device-tests'
  if not (origin/'dispatch_manifest.json').is_file():self.skipTest('dispatch artifact absent')
  with tempfile.TemporaryDirectory() as temporary:
   root=isolated_device_root(temporary)
   def fake(argv,seconds,name,cfg,**kwargs):
    log=Path(temporary)/name
    text='List of devices attached\nserial123 device\n' if name=='device-dispatch-list' else ''
    Path(str(log)+'.stdout.log').write_text(text,encoding='utf-8')
    return {'returncode':1 if name=='device-dispatch-session' else 0,'timed_out':False,'log':str(log)}
   with patch.object(worksafe,'ROOT',root),patch.object(worksafe,'available_memory_mb',return_value=2048),patch.object(worksafe,'_run_job',side_effect=fake),patch('secrets.token_hex',return_value='abc123'):
    with self.assertRaises(worksafe.WorkSafeError):worksafe.run_android_dispatch_single_session()
   attempt=json.loads((root/'logs/device-dispatch-attempt.json').read_text(encoding='utf-8'))
   self.assertEqual(attempt,{'remote_directory':'/data/local/tmp/mhae_abc123','cleanup':'unconfirmed'})
 def test_diagnostic_install_rejects_existing_package(self):
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary);(root/'config').mkdir();(root/'build/android-diagnostic-apk').mkdir(parents=True)
   (root/'config/work_safe.json').write_bytes((worksafe.ROOT/'config/work_safe.json').read_bytes())
   (root/'build/android-diagnostic-apk/diagnostic-debug.apk').write_bytes(b'test')
   calls=[]
   def fake(argv,seconds,name,cfg,**kwargs):
    calls.append(name); log=root/name
    Path(str(log)+'.stdout.log').write_text('List of devices attached\nserial123 device\n' if name=='diagnostic-device-list' else '',encoding='utf-8')
    return {'returncode':72 if name=='diagnostic-install-preflight' else 0,'timed_out':False,'log':str(log)}
   with patch.object(worksafe,'ROOT',root),patch.object(worksafe,'available_memory_mb',return_value=2048),patch.object(worksafe,'_run_job',side_effect=fake):
    with self.assertRaises(worksafe.WorkSafeError): worksafe.install_diagnostic_on_s25()
   self.assertEqual(calls,['diagnostic-device-list','diagnostic-install-preflight'])

if __name__ == '__main__': unittest.main(verbosity=2)
