import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import bundle_resources as resources


class BundleResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="relocated app ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.adb = self.root / "platform-tools" / "adb"
        self.adb.parent.mkdir()
        self.adb.write_bytes(b"synthetic binary")
        self.apk = self.root / "CU-Denver-Equity-Kiosk.apk"
        with zipfile.ZipFile(self.apk, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"synthetic manifest")
            archive.writestr("classes.dex", b"synthetic dex")
        self.digest = hashlib.sha256(self.apk.read_bytes()).hexdigest()
        for name, value in (("frozen", True), ("_MEIPASS", str(self.root)), ("platform", "darwin")):
            context = patch.object(sys, name, value, create=True)
            context.start()
            self.addCleanup(context.stop)
        self.runner = patch.object(resources.subprocess, "run")
        self.run = self.runner.start()
        self.addCleanup(self.runner.stop)
        self.run.return_value = subprocess.CompletedProcess([], 0, "Android Debug Bridge version 1.0.41\n", "")
        for name, value in (("platform", "synthetic-macOS"), ("machine", "synthetic-architecture")):
            context = patch.object(resources.platform, name, return_value=value)
            context.start()
            self.addCleanup(context.stop)

    def test_frozen_paths_ignore_environment_and_working_directory(self):
        with patch.dict(os.environ, {"KIOSK_RELEASE_APK": "unreviewed-sibling.apk"}):
            root, adb, apk = resources.resource_paths()
        self.assertEqual((root, adb, apk), (str(self.root), str(self.adb), str(self.apk)))

    def test_relocated_resources_pass_and_only_adb_version_runs(self):
        report = resources.check_bundle(self.digest.upper())
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["apk_sha256"], self.digest)
        self.run.assert_called_once_with([str(self.adb), "version"], capture_output=True,
                                         text=True, timeout=15, check=True)

    def test_missing_bundled_apk_does_not_use_environment_copy(self):
        sibling = self.root / "manual.apk"
        self.apk.rename(sibling)
        with patch.dict(os.environ, {"KIOSK_RELEASE_APK": str(sibling)}):
            with self.assertRaisesRegex(ValueError, "Missing or empty"):
                resources.check_bundle(self.digest)
        self.run.assert_not_called()

    def test_missing_or_empty_adb_fails_before_execution(self):
        self.adb.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "Missing or empty"):
            resources.check_bundle(self.digest)
        self.adb.unlink()
        with self.assertRaisesRegex(ValueError, "Missing or empty"):
            resources.check_bundle(self.digest)
        self.run.assert_not_called()

    def test_changed_apk_rejected(self):
        with self.assertRaisesRegex(ValueError, "SHA-256 differs"):
            resources.check_bundle("0" * 64)
        self.run.assert_not_called()

    def test_incomplete_apk_rejected_even_with_matching_hash(self):
        with zipfile.ZipFile(self.apk, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"synthetic manifest")
        digest = hashlib.sha256(self.apk.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "incomplete or corrupt"):
            resources.check_bundle(digest)

    def test_wrong_architecture_or_failed_adb_rejected(self):
        self.run.side_effect = OSError("Exec format error")
        report = self.root / "failure.json"
        self.assertEqual(resources.main(["--expected-apk-sha256", self.digest,
                                         "--report", str(report)]), 1)
        self.assertEqual(json.loads(report.read_text())["status"], "FAIL")

    def test_adb_timeout_and_nonzero_exit_rejected(self):
        for error in (subprocess.TimeoutExpired("adb", 15), subprocess.CalledProcessError(1, "adb")):
            self.run.side_effect = error
            with self.assertRaises(subprocess.SubprocessError):
                resources.check_bundle(self.digest)

    def test_unexpected_adb_output_rejected(self):
        self.run.return_value.stdout = "unrelated program"
        with self.assertRaisesRegex(ValueError, "did not report"):
            resources.check_bundle(self.digest)

    def test_source_cannot_pass_as_frozen_acceptance(self):
        with patch.object(sys, "frozen", False):
            with self.assertRaisesRegex(ValueError, "requires the frozen"):
                resources.check_bundle(self.digest)
            with patch.dict(os.environ, {"KIOSK_RELEASE_APK": "reviewed-source.apk"}):
                self.assertEqual(resources.resource_paths()[2], "reviewed-source.apk")

    def test_macos_internal_resource_symlink_is_supported(self):
        contents = self.root / "Relocated Manager.app" / "Contents"
        frameworks = contents / "Frameworks"
        data = contents / "Resources"
        frameworks.mkdir(parents=True)
        data.mkdir()
        link = frameworks / self.apk.name
        try:
            link.symlink_to(data / self.apk.name)
        except OSError as exc:
            self.skipTest("Host cannot create macOS-style symlink: " + str(exc))
        self.apk.rename(data / self.apk.name)
        self.adb.parent.rename(frameworks / "platform-tools")
        with patch.object(sys, "_MEIPASS", str(frameworks)):
            self.assertEqual(resources.check_bundle(self.digest)["status"], "PASS")

    def test_symlink_outside_bundle_is_rejected(self):
        nested = self.root / "bundle"
        nested.mkdir()
        try:
            (nested / self.apk.name).symlink_to(self.apk)
        except OSError as exc:
            self.skipTest("Host cannot create external resource symlink: " + str(exc))
        self.adb.parent.rename(nested / "platform-tools")
        with patch.object(sys, "_MEIPASS", str(nested)):
            with self.assertRaisesRegex(ValueError, "outside the frozen bundle"):
                resources.check_bundle(self.digest)

    def test_cli_uses_same_resource_check_without_creating_gui(self):
        report = self.root / "resources.json"
        args = ["kiosk-manager.py", "--check-bundle", "--expected-apk-sha256", self.digest,
                "--report", str(report)]
        with patch.object(sys, "argv", args), self.assertRaises(SystemExit) as result:
            runpy.run_path(str(Path(__file__).resolve().parents[1] / "kiosk-manager.py"), run_name="__main__")
        self.assertEqual(result.exception.code, 0)
        self.assertEqual(json.loads(report.read_text())["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
