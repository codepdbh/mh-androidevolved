"""Ensure stale nested sources invalidate private ARM64 harness evidence."""
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import worksafe

class TimeInputHashesTests(unittest.TestCase):
    def test_alternate_harness_entry_tracks_private_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'tests').mkdir();folder=root/'private/analysis/candidate_time/dependencies';folder.mkdir(parents=True)
            entry=root/'tests/other.c';entry.write_text('#include "helper.c"\n')
            (folder/'helper.c').write_text('/* private local translation */\n')
            with patch.object(worksafe,'ROOT',root):
                hashes=worksafe._time_harness_input_hashes(entry)
            self.assertEqual(set(hashes),{'tests/other.c','private/analysis/candidate_time/dependencies/helper.c'})

    def test_stale_or_legacy_manifest_rejected_before_adb(self):
        for recorded in (None,{'recomp/x87_semantics.h':'old'}):
            with self.subTest(recorded=recorded),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);(root/'config').mkdir();(root/'tests').mkdir()
                (root/'config/work_safe.json').write_text('{"enabled":true}')
                harness=b'/* unchanged main file */';(root/'tests/time_candidate_native.c').write_bytes(harness)
                base=root/'private/analysis/candidate_time';binary=base/'android/time_test';binary.parent.mkdir(parents=True)
                binary.write_bytes(b'synthetic binary fixture, never executed')
                manifest={'abi':'arm64-v8a','name':'time_test','sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
                          'harness_sha256':hashlib.sha256(harness).hexdigest()}
                if recorded is not None:manifest['source_inputs']=recorded
                (binary.parent/'manifest.json').write_text(json.dumps(manifest))
                with patch.object(worksafe,'ROOT',root),patch.object(worksafe,'available_memory_mb',return_value=2048),\
                     patch.object(worksafe,'_time_arm64_paths',return_value=(base,binary)),\
                     patch.object(worksafe,'_time_harness_input_hashes',return_value={'recomp/x87_semantics.h':'new'}),\
                     patch.object(worksafe,'_run_job') as run,patch.object(Path,'is_file',return_value=True):
                    with self.assertRaisesRegex(worksafe.WorkSafeError,'inputs changed or unrecorded'):
                        worksafe.run_time_candidate_on_s25()
                    run.assert_not_called()

    def test_nested_header_change_and_include_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'tests').mkdir();(root/'recomp').mkdir()
            (root/'tests/time_candidate_native.c').write_text('#include "adapter.h"\n')
            (root/'recomp/adapter.h').write_text('#include "math.h"\n')
            header=root/'recomp/math.h';header.write_text('#include "adapter.h"\n#define VALUE 1\n')
            with patch.object(worksafe,'ROOT',root):
                before=worksafe._time_harness_input_hashes()
                self.assertEqual(len(before),3)
                header.write_text('#include "adapter.h"\n#define VALUE 2\n')
                after=worksafe._time_harness_input_hashes()
                self.assertNotEqual(before,after)
                self.assertEqual(before['tests/time_candidate_native.c'],after['tests/time_candidate_native.c'])

    def test_missing_include_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'tests').mkdir()
            (root/'tests/time_candidate_native.c').write_text('#include "missing.h"\n')
            with patch.object(worksafe,'ROOT',root),self.assertRaises(worksafe.WorkSafeError):
                worksafe._time_harness_input_hashes()

    def test_include_outside_workspace_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp);root=parent/'workspace';(root/'tests').mkdir(parents=True)
            (parent/'outside.h').write_text('/* external */\n')
            (root/'tests/time_candidate_native.c').write_text('#include "../../outside.h"\n')
            with patch.object(worksafe,'ROOT',root),self.assertRaises(worksafe.WorkSafeError):
                worksafe._time_harness_input_hashes()

if __name__=='__main__':unittest.main()
