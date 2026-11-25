"""Reject stale validation/build records before any compiler or ADB process starts."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import worksafe


class GameBuildInputsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / 'private/analysis/winmain'
        self.game = self.root / 'private/analysis/game/android'
        files = {
            'config/work_safe.json': '{"enabled": true}',
            'tests/winmain_native.c': '#include "shared.h"\n',
            'runtime/shared.h': '#define MODEL 1\n',
            'tests/compare_harness.py': '# fixture comparator\n',
            'private/analysis/winmain/winmain_unit.c': '/* synthetic unit */\n',
            'private/analysis/winmain/x86_reference.json': '{}',
            'private/analysis/winmain/scenarios/save/x86_reference.json': '{}',
            'private/analysis/winmain/seed_saves/slot.sav': 'synthetic seed',
            'private/analysis/winmain/android/winmain_test': 'synthetic binary',
            'android/app/src/main/cpp/game_jni.c': '#include "shared.h"\n',
            'private/analysis/game/android/libmh_game.so': 'synthetic library',
        }
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        self.patch = patch.object(worksafe, 'ROOT', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        (self.base / 'winmain_report.json').write_text(json.dumps({
            'unit_sha256': self.digest(self.base / 'winmain_unit.c')}))
        self.validation = self.base / 'android/validated.json'
        self.validation.write_text(json.dumps({
            'source_inputs': worksafe._winmain_input_hashes(),
            'binary_sha256': self.digest(self.base / 'android/winmain_test')}))
        (self.game / 'built.json').write_text(json.dumps({
            'source_inputs': worksafe._game_library_input_hashes(),
            'validation_sha256': self.digest(self.validation),
            'library_sha256': self.digest(self.game / 'libmh_game.so')}))
        (self.game / 'prepared.json').write_text(json.dumps({
            'source_inputs': worksafe._game_library_input_hashes(),
            'winmain_inputs': worksafe._winmain_input_hashes(),
            'library_sha256': self.digest(self.game / 'libmh_game.so')}))

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_current_records_accept_exact_inputs(self):
        self.assertEqual(worksafe._require_current_game_library(), self.game / 'libmh_game.so')

    def test_shared_source_reference_and_seed_changes_reject_before_build(self):
        for name in ('runtime/shared.h', 'tests/compare_harness.py',
                     'private/analysis/winmain/scenarios/save/x86_reference.json',
                     'private/analysis/winmain/seed_saves/slot.sav'):
            path = self.root / name
            old = path.read_bytes()
            with self.subTest(name=name):
                path.write_bytes(old + b'changed')
                with patch.object(worksafe, '_run_job') as run:
                    with self.assertRaisesRegex(worksafe.WorkSafeError, 'inputs changed'):
                        worksafe.build_game_library()
                    run.assert_not_called()
            path.write_bytes(old)

    def test_missing_source_record_requires_revalidation(self):
        self.validation.write_text('{}')
        with self.assertRaisesRegex(worksafe.WorkSafeError, 'unrecorded'):
            worksafe._require_validated_winmain()

    def test_replaced_validated_binary_rejected(self):
        (self.base / 'android/winmain_test').write_bytes(b'other binary')
        with self.assertRaisesRegex(worksafe.WorkSafeError, 'binary changed'):
            worksafe._require_validated_winmain()

    def test_changed_jni_rejected_even_when_timestamp_is_preserved(self):
        path = self.root / 'android/app/src/main/cpp/game_jni.c'
        import os
        timestamp = path.stat().st_mtime_ns
        path.write_text('/* changed JNI */')
        os.utime(path, ns=(timestamp, timestamp))
        with self.assertRaisesRegex(worksafe.WorkSafeError, 'inputs changed'):
            worksafe._require_current_game_library()

    def test_replaced_library_rejected(self):
        (self.game / 'libmh_game.so').write_bytes(b'other library')
        with self.assertRaisesRegex(worksafe.WorkSafeError, 'binary changed'):
            worksafe._require_current_game_library()

    def test_removed_scenario_requires_revalidation(self):
        (self.base / 'scenarios/save/x86_reference.json').unlink()
        with self.assertRaisesRegex(worksafe.WorkSafeError, 'inputs changed'):
            worksafe._require_validated_winmain()

    def test_prepared_library_requires_finished_device_validation(self):
        self.validation.unlink()
        before = (self.game / 'built.json').read_bytes()
        with self.assertRaisesRegex(worksafe.WorkSafeError, 'not been validated'):
            worksafe.promote_prepared_game_library()
        self.assertEqual((self.game / 'built.json').read_bytes(), before)

    def test_prepared_library_rejects_changed_jni(self):
        (self.root / 'android/app/src/main/cpp/game_jni.c').write_text('/* changed */')
        with self.assertRaisesRegex(worksafe.WorkSafeError, 'inputs changed'):
            worksafe.promote_prepared_game_library()

    def test_prepared_library_rejects_changed_binary(self):
        (self.game / 'libmh_game.so').write_bytes(b'changed')
        with self.assertRaisesRegex(worksafe.WorkSafeError, 'binary changed'):
            worksafe.promote_prepared_game_library()

    def make_checkpoint(self):
        host = self.base / 'winmain-test.exe'
        host.write_bytes(b'synthetic host')
        (self.root / 'logs').mkdir()
        outputs = {}
        for name in ('main', 'save'):
            path = self.root / f'logs/winmain-{name}-host-run.stdout.log'
            path.write_text('{"fixture": 1}\n')
            outputs[name] = self.digest(path)
        (self.base / 'android/pending-validation.json').write_text(json.dumps({
            'source_inputs': worksafe._winmain_input_hashes(),
            'binary_sha256': self.digest(self.base / 'android/winmain_test'),
            'host_binary_sha256': self.digest(host), 'host_output_sha256': outputs,
            'output_sha256': {}}))

    def test_pending_checkpoint_rejects_changed_source_before_processes(self):
        self.make_checkpoint()
        (self.root / 'runtime/shared.h').write_text('/* changed */')
        with patch.object(worksafe, '_run_job') as run:
            with self.assertRaisesRegex(worksafe.WorkSafeError, 'inputs changed'):
                worksafe.resume_winmain_on_s25()
            run.assert_not_called()

    def test_pending_checkpoint_rejects_changed_binary_before_processes(self):
        self.make_checkpoint()
        (self.base / 'android/winmain_test').write_bytes(b'changed')
        with patch.object(worksafe, '_run_job') as run:
            with self.assertRaisesRegex(worksafe.WorkSafeError, 'binary changed'):
                worksafe.resume_winmain_on_s25()
            run.assert_not_called()

    def test_pending_checkpoint_rejects_changed_host_output_before_device(self):
        self.make_checkpoint()
        (self.root / 'logs/winmain-main-host-run.stdout.log').write_text('changed')
        with patch.object(worksafe, '_run_job') as run:
            with self.assertRaisesRegex(worksafe.WorkSafeError, 'host output changed'):
                worksafe.resume_winmain_on_s25()
            run.assert_not_called()

    def make_prepared_apk(self, library=b'synthetic library'):
        import zipfile
        out = self.root / 'build/android-diagnostic-apk'
        out.mkdir(parents=True)
        java = self.root / 'android/app/src/main/java/MainActivity.java'
        java.parent.mkdir(parents=True)
        java.write_text('/* fixture */')
        path = out / 'prepared-debug.apk'
        with zipfile.ZipFile(path, 'w') as apk:
            apk.writestr('lib/arm64-v8a/libmh_game.so', library)
        (out / 'prepared-apk.json').write_text(json.dumps({
            'apk_sha256': self.digest(path), 'app_inputs': worksafe._android_app_input_hashes()}))
        return out

    def test_prepared_apk_finalizes_only_with_current_library(self):
        out = self.make_prepared_apk()
        worksafe.finalize_prepared_apk()
        self.assertEqual((out / 'prepared-debug.apk').read_bytes(), (out / 'diagnostic-debug.apk').read_bytes())

    def test_prepared_apk_cannot_finalize_without_device_validation(self):
        out = self.make_prepared_apk()
        self.validation.unlink()
        with self.assertRaisesRegex(worksafe.WorkSafeError, 'not been validated'):
            worksafe.finalize_prepared_apk()
        self.assertFalse((out / 'diagnostic-debug.apk').exists())

    def test_prepared_apk_rejects_changed_java(self):
        self.make_prepared_apk()
        (self.root / 'android/app/src/main/java/MainActivity.java').write_text('/* changed */')
        with self.assertRaisesRegex(worksafe.WorkSafeError, 'APK inputs changed'):
            worksafe.finalize_prepared_apk()

    def test_prepared_apk_rejects_different_native_payload(self):
        self.make_prepared_apk(b'different library')
        with self.assertRaisesRegex(worksafe.WorkSafeError, 'different game library'):
            worksafe.finalize_prepared_apk()


if __name__ == '__main__':
    unittest.main()
