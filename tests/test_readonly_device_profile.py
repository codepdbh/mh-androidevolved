"""Construct both fixed device scripts with simulated ADB, never a real device."""
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import worksafe

def fixture(root):
    (root/'config').mkdir();(root/'config/work_safe.json').write_text('{"enabled":true}')
    (root/'logs').mkdir();folder=root/'private/analysis/candidate_time/dependencies';folder.mkdir(parents=True)
    items=[];parts=[]
    for i,address in enumerate(('0x605e40','0x60fea0','0x60ff60')):
        name=f'dep_{int(address,16):08x}_precise.c';content=f'/* synthetic source fixture {i} */'
        (folder/name).write_text(content+'\n');parts.append(content)
        items.append({'address':address,'source':name,'adapted_sha256':hashlib.sha256(content.encode()).hexdigest()})
    (folder/'loader_helpers_report.json').write_text(json.dumps({'items':items}))
    header='#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n#include "checked_memory_adapter.h"\n#include "checked_dispatch_adapter.h"\n'
    (folder/'loader_helpers_unit.c').write_text(header+'\n'.join(parts)+'\n')
    binary=bytearray(64);binary[:6]=b'\x7fELF\x02\x01';binary[16:20]=b'\x03\x00\xb7\x00'
    for name in ('readonly-stream','readonly-handles'):(folder/(name+'-device-test')).write_bytes(binary)

class ReadonlyDeviceProfileTests(unittest.TestCase):
    def test_both_scripts_construct_and_report_explicit_skips(self):
        for handles in (False,True):
            with self.subTest(handles=handles),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);fixture(root);calls=[]
                def fake(argv,seconds,name,cfg,**kwargs):
                    calls.append((name,kwargs));log=root/'logs'/name
                    output='List of devices attached\nserial123 device\n' if name.endswith('device-list') else ''
                    if name.endswith('device-session'):
                        output='MHAE_MODEL=SM-S938B\nMHAE_TESTS_PASSED\nMHAE_CLEANUP_OK\n'+('MHAE_FIFO_UNAVAILABLE\n' if handles else '')
                    Path(str(log)+'.stdout.log').write_text(output)
                    return {'returncode':0,'timed_out':False,'log':str(log)}
                with patch.object(worksafe,'ROOT',root),patch.object(worksafe,'available_memory_mb',return_value=2048),\
                     patch.object(worksafe,'_time_harness_input_hashes',return_value={'fixture':'hash'}),\
                     patch.object(worksafe,'prepare_file_lifecycle_low_memory') as prepare,\
                     patch.object(worksafe,'_run_job',side_effect=fake),patch.object(Path,'is_file',return_value=True):
                    result=worksafe.run_real_readonly_stream_s25(with_handles=handles)
                self.assertEqual(prepare.call_count,int(handles));self.assertEqual(result['cleanup'],'confirmed')
                self.assertEqual(bool(result['skipped']),handles)
                scripts=[kwargs['input_bytes'] for name,kwargs in calls if name.endswith('shell-check') or name.endswith('device-session')]
                self.assertEqual(len(scripts),2);self.assertEqual(scripts[0],scripts[1])
                script=scripts[0].decode('ascii');self.assertNotIn('rm -r',script)
                self.assertLess(script.index('case "$model"'),script.index('mkdir "$d"'))
                self.assertIn('sha256sum "$game"',script)
                self.assertIn('"$p" "$d"' if handles else '"$p" "$f"',script)

    def test_changed_sources_stop_before_adb(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fixture(root);calls=[]
            def fake(argv,seconds,name,cfg,**kwargs):
                calls.append(name);return {'returncode':0,'timed_out':False,'log':'unused'}
            with patch.object(worksafe,'ROOT',root),patch.object(worksafe,'available_memory_mb',return_value=2048),\
                 patch.object(worksafe,'_time_harness_input_hashes',side_effect=[{'a':'old'},{'a':'new'}]),\
                 patch.object(worksafe,'_run_job',side_effect=fake),patch.object(Path,'is_file',return_value=True):
                with self.assertRaisesRegex(worksafe.WorkSafeError,'sources changed while compiling'):
                    worksafe.run_real_readonly_stream_s25()
            self.assertEqual(calls,['readonly-stream-device-build'])

if __name__=='__main__':unittest.main()
