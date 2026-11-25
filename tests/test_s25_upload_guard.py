"""No uploads to another model, and no unsafe names in seeded saves."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import worksafe


class S25UploadGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'config').mkdir()
        (self.root / 'logs').mkdir()
        (self.root / 'config/work_safe.json').write_text('{"enabled": true}')
        self.patch = patch.object(worksafe, 'ROOT', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.calls = []

    @staticmethod
    def binary(size):
        data = bytearray(size)
        data[:4] = b'\x7fELF'
        data[18:20] = (183).to_bytes(2, 'little')
        return bytes(data)

    def fake_run(self, argv, seconds, name, cfg, **kwargs):
        self.calls.append(name)
        path = self.root / name
        output = 'List of devices attached\nserial123 device\n' if name.endswith('-list') else 'Redmi Note 8\n'
        Path(str(path) + '.stdout.log').write_text(output)
        return {'returncode': 0, 'timed_out': False, 'log': str(path)}

    def test_other_model_rejected_before_small_or_large_upload(self):
        for size in (64, 1024 * 1024 + 1):
            self.calls.clear()
            with self.subTest(size=size), patch.object(worksafe, '_run_job', side_effect=self.fake_run), patch.object(Path, 'is_file', return_value=True):
                with self.assertRaisesRegex(worksafe.WorkSafeError, 'nothing uploaded'):
                    worksafe._run_binary_on_s25(self.binary(size), 'proof')
            self.assertEqual(self.calls, ['device-proof-list', 'device-proof-model'])

    def test_hidden_or_parent_save_names_rejected_before_processes(self):
        for name in ('.hidden', '..', '../slot', 'slot/other'):
            with self.subTest(name=name), patch.object(worksafe, '_run_job') as run:
                with self.assertRaisesRegex(worksafe.WorkSafeError, 'invalid device saves'):
                    worksafe._run_binary_on_s25(self.binary(64), 'proof', saves={name: b'data'})
                run.assert_not_called()

    def test_disabled_supervisor_rejects_before_processes(self):
        (self.root / 'config/work_safe.json').write_text('{"enabled": false}')
        with patch.object(worksafe, '_run_job') as run:
            with self.assertRaisesRegex(worksafe.WorkSafeError, 'work-safe mode required'):
                worksafe._run_binary_on_s25(self.binary(64), 'proof')
            run.assert_not_called()

    def test_supported_s25_can_complete_bounded_session(self):
        def fake(argv, seconds, name, cfg, **kwargs):
            path = self.root / name
            output = ('List of devices attached\nserial123 device\n' if name.endswith('-list') else
                      'SM-S938B\n' if name.endswith('-model') else
                      'MHAE_BEGIN\nfixture passed\nMHAE_END\nMHAE_TESTS_PASSED\nMHAE_CLEANUP_OK\n')
            Path(str(path) + '.stdout.log').write_text(output)
            return {'returncode': 0, 'timed_out': False, 'log': str(path)}
        with patch.object(worksafe, '_run_job', side_effect=fake), patch.object(Path, 'is_file', return_value=True):
            self.assertEqual(worksafe._run_binary_on_s25(self.binary(64), 'proof').strip(), 'fixture passed')
        attempt = json.loads((self.root / 'logs/device-proof-attempt.json').read_text())
        self.assertEqual(attempt['serial'], 'serial123')
        self.assertEqual(attempt['cleanup'], 'confirmed')

    def test_interrupted_cleanup_rejects_unexpected_directory(self):
        with patch.object(worksafe, '_run_job') as run:
            with self.assertRaisesRegex(worksafe.WorkSafeError, 'unrecorded'):
                worksafe._finish_interrupted_winmain_cleanup(
                    {'remote_directory': '/sdcard/mh-androidevolved', 'serial': 'serial123'}, '0' * 64, {})
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
