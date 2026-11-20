"""Classification of `adb install -r` results in kiosk-manager.py (§7.1)."""
import importlib.util
import pathlib
import sys
import types
import unittest

try:
    import tkinter  # noqa: F401
except ImportError:  # headless CI: the classifier itself needs no GUI
    stub = types.ModuleType("tkinter")
    for name in ("ttk", "messagebox", "scrolledtext"):
        setattr(stub, name, types.ModuleType(f"tkinter.{name}"))
        sys.modules[f"tkinter.{name}"] = getattr(stub, name)
    sys.modules["tkinter"] = stub

_path = pathlib.Path(__file__).resolve().parent.parent / "kiosk-manager.py"
_spec = importlib.util.spec_from_file_location("kiosk_manager", _path)
kiosk_manager = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kiosk_manager)
classify = kiosk_manager.install_failure_message


class InstallFailureMessageTest(unittest.TestCase):
    def test_success(self):
        self.assertIsNone(classify("Performing Streamed Install\nSuccess\n", "", 0))

    def test_signer_mismatch_points_to_inventory_and_reprovisioning(self):
        err = ("adb: failed to install CU-Denver-Equity-Kiosk.apk: Failure "
               "[INSTALL_FAILED_UPDATE_INCOMPATIBLE: Existing package com.example.webkiosk "
               "signatures do not match newer version; ignoring!]\n")
        msg = classify("Performing Streamed Install\n", err, 1)
        self.assertIn("INSTALL_FAILED_UPDATE_INCOMPATIBLE", msg)
        self.assertIn("NOT uninstalled", msg)
        self.assertIn("signer inventory", msg)
        self.assertIn("reprovisioning", msg)

    def test_other_install_failure_reports_code(self):
        msg = classify("", "adb: failed to install x.apk: Failure [INSTALL_FAILED_VERSION_DOWNGRADE]", 1)
        self.assertIn("INSTALL_FAILED_VERSION_DOWNGRADE", msg)
        self.assertIn("NOT uninstalled", msg)

    def test_failure_with_zero_exit_code(self):
        self.assertIsNotNone(classify("Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]\n", "", 0))

    def test_timeout_or_missing_device(self):
        self.assertIn("Command timed out", classify("", "Command timed out", 1))
        self.assertIn("adb exit code 1", classify("", "", 1))


if __name__ == "__main__":
    unittest.main()
