import importlib.util
import io
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import package_policy
import provisioning as p


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("kiosk_manager", ROOT / "kiosk-manager.py")
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


class FakeAdb:
    """A stateful host fixture. No subprocess or real ADB is invoked."""

    def __init__(self):
        self.calls = []
        self.rows = "List of devices attached\nTABLET-1 device model:Synthetic\n"
        self.owner = None
        self.home = "com.vendor.home/.Home"
        self.disabled = set()
        self.fail = None
        self.locked = False
        self.start_locked = True
        self.policy_packages = set(p.LOCK_PACKAGES)
        self.features = 0
        self.user = "0"
        self.package_user = "installed=true hidden=false suspended=false enabled=0"
        self.install_result = ("Success\n", "", 0)
        self.set_owner = True
        self.set_home = True

    def policy(self):
        text = "Current Device Policy Manager state:\n"
        if self.owner:
            text += f"  Device Owner:\n    admin=ComponentInfo{{{self.owner}}}\n    User ID: 0\n"
        return text

    def activities(self):
        state = "LOCKED" if self.locked else "NONE"
        return (
            f"topResumedActivity=ActivityRecord{{fff u0 {p.HOME} t1}}\n"
            f"  mLockTaskModeState={state}\n"
            f"  mLockTaskModeTasks=\n    #0 Task{{a A=10000:{p.PACKAGE} U=0}}\n"
            "  mLockTaskPackages (userId:packages)=\n"
            f"    u0:[{', '.join(sorted(self.policy_packages))}]\n"
            f"  mLockTaskFeatures (userId:flags)=\n    u0:{self.features}\n"
        )

    def __call__(self, arguments, timeout=30):
        self.calls.append(list(arguments))
        if arguments[1:] == ["devices", "-l"]:
            return self.rows, "", 0
        if arguments[1:3] != ["-s", "TABLET-1"]:
            raise AssertionError(f"Unbound/wrong device command: {arguments}")
        command = arguments[3:]
        text = " ".join(command)
        if self.fail and self.fail in text:
            return "", "synthetic failure", 1
        if command == ["shell", "am", "get-current-user"]:
            return self.user, "", 0
        if command == ["shell", "dumpsys", "device_policy"]:
            return self.policy(), "", 0
        if command == ["shell", "dumpsys", "user"]:
            return "Users:\n  UserInfo{0:Owner:c13}\n    Effective restrictions:\n" + "".join(
                f"      {restriction}\n" for restriction in sorted(p.RESTRICTIONS)
            ), "", 0
        if command[:2] == ["install", "-r"]:
            return self.install_result
        if command[:3] == ["shell", "dpm", "set-device-owner"]:
            if self.set_owner:
                self.owner = p.ADMIN
            return "Success", "", 0
        if command[:3] == ["shell", "dumpsys", "package"]:
            return f"Package [{command[-1]}]\n User 0: {self.package_user}\n", "", 0
        if "query-activities" in command:
            return "com.google.android.youtube/.HomeActivity\ncom.vendor.unknown/.Home\n", "", 0
        if command[:3] == ["shell", "settings", "get"]:
            return "null", "", 0
        if command == ["shell", "pm", "list", "packages", "-d", "--user", "0"]:
            return "".join(f"package:{pkg}\n" for pkg in self.disabled), "", 0
        if command[:3] == ["shell", "pm", "disable-user"]:
            self.disabled.add(command[-1])
            return "", "", 0
        if command[:3] == ["shell", "pm", "enable"]:
            self.disabled.discard(command[-1])
            return "", "", 0
        if command[:4] == ["shell", "cmd", "package", "set-home-activity"]:
            if self.set_home:
                self.home = command[-1]
            return "Success", "", 0
        if "resolve-activity" in command:
            return self.home, "", 0
        if command[:3] == ["shell", "am", "start"]:
            self.locked = self.start_locked
            return "Status: ok\n", "", 0
        if command == ["shell", "dumpsys", "activity", "activities"]:
            return self.activities(), "", 0
        if command[:3] == ["shell", "am", "force-stop"]:
            self.locked = False
            return "", "", 0
        raise AssertionError(f"Unexpected command: {arguments}")


class ProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.apk = Path(self.temp.name) / "reviewed builds" / "kiosk.apk"
        self.apk.parent.mkdir()
        self.apk.write_bytes(b"synthetic host fixture, not an APK")
        self.state = Path(self.temp.name) / "state.json"
        self.fake = FakeAdb()
        self.client = p.AdbClient("C:/ADB tools/adb.exe", self.fake)
        self.sleep = patch.object(p.time, "sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def setup_device(self):
        p.setup(self.client.select("TABLET-1"), self.apk, self.state)

    def test_device_states_and_explicit_selection(self):
        for output in (
            "List of devices attached\n",
            "List of devices attached\nA unauthorized\nB offline\n",
            "List of devices attached\nA device\nB device\n",
            "List of devices attached\nA recovery\n",
        ):
            with self.subTest(output=output), self.assertRaises(p.ProvisioningError):
                p.select_device(p.parse_devices(output))
        rows = p.parse_devices("List of devices attached\nA unauthorized\nB device product:x\n")
        self.assertEqual(p.select_device(rows), "B")
        self.assertEqual(p.select_device(rows, "B"), "B")
        for serial in ("A", "C"):
            with self.assertRaises(p.ProvisioningError):
                p.select_device(rows, serial)

    def test_discovery_failure_stops_before_device_commands(self):
        client = p.AdbClient("adb", lambda *args, **kwargs: ("List of devices attached", "offline", 1))
        with self.assertRaises(p.ProvisioningError):
            client.select()

    def test_malformed_and_duplicate_rows_fail(self):
        for output in ("garbage", "A device\nA device", "-s device"):
            with self.subTest(output=output), self.assertRaises(p.ProvisioningError):
                p.parse_devices(output)

    def test_success_second_pass_and_every_command_bound(self):
        self.setup_device()
        recorded = self.state.read_bytes()
        self.setup_device()
        self.assertEqual(self.state.read_bytes(), recorded)
        self.assertEqual(self.fake.owner, p.ADMIN)
        self.assertEqual(self.fake.home, p.HOME)
        self.assertEqual(self.fake.disabled, {"com.google.android.youtube"})
        self.assertEqual(sum("set-device-owner" in cmd for cmd in self.fake.calls), 1)
        for command in self.fake.calls:
            if command[1:] != ["devices", "-l"]:
                self.assertEqual(command[1:3], ["-s", "TABLET-1"])
        install = next(cmd for cmd in self.fake.calls if "install" in cmd)
        self.assertEqual(install[-1], str(self.apk.resolve()))

    def test_install_failures_never_uninstall_or_enroll(self):
        for result in (
            ("", "Command timed out", 1),
            ("Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]", "", 1),
            ("Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]", "", 0),
            ("Failure [INSTALL_FAILED_INVALID_APK]", "", 1),
            ("not confirmed", "", 0),
            ("Success", "adb failure", 1),
        ):
            with self.subTest(result=result):
                self.fake.calls.clear()
                self.fake.install_result = result
                with self.assertRaises(p.ProvisioningError):
                    self.setup_device()
                self.assertFalse(any("uninstall" in cmd or "set-device-owner" in cmd for cmd in self.fake.calls))

    def test_other_owner_stops_before_install(self):
        for owner in ("com.afwsamples.testdpc/.DeviceAdminReceiver", p.PACKAGE + "/.WrongReceiver"):
            with self.subTest(owner=owner):
                self.fake.calls.clear()
                self.fake.owner = owner
                with self.assertRaises(p.ProvisioningError):
                    self.setup_device()
                self.assertFalse(any("install" in cmd for cmd in self.fake.calls))

    def test_generic_success_does_not_prove_owner_or_home(self):
        self.fake.set_owner = False
        with self.assertRaises(p.ProvisioningError):
            self.setup_device()
        self.assertFalse(any("set-home-activity" in cmd for cmd in self.fake.calls))
        self.fake.set_owner = True
        self.fake.set_home = False
        with self.assertRaises(p.ProvisioningError):
            self.setup_device()
        self.assertFalse(any("start" in cmd for cmd in self.fake.calls))

    def test_failed_steps_stop_dependent_commands(self):
        for failed, forbidden in (
            ("set-device-owner", "query-activities"),
            ("set-home-activity", "start"),
            ("disable-user", "set-home-activity"),
            ("get-current-user", "install"),
            ("settings get", "disable-user"),
            ("am start", "activities"),
        ):
            with self.subTest(failed=failed):
                self.fake = FakeAdb()
                self.fake.fail = failed
                self.client.runner = self.fake
                with self.assertRaises(p.ProvisioningError):
                    self.setup_device()
                self.assertFalse(any(forbidden in cmd for cmd in self.fake.calls))

    def test_no_home_change_when_required_app_unavailable(self):
        for state in (
            "installed=false hidden=false suspended=false enabled=0",
            "installed=true hidden=true suspended=false enabled=0",
            "installed=true hidden=false suspended=true enabled=0",
            "installed=true hidden=false suspended=false enabled=3",
            "unrecognized",
        ):
            with self.subTest(state=state):
                self.fake.calls.clear()
                self.fake.package_user = state
                with self.assertRaises(p.ProvisioningError):
                    self.setup_device()
                self.assertFalse(any("set-home-activity" in cmd for cmd in self.fake.calls))

    def test_non_primary_user_rejected(self):
        self.fake.user = "10"
        with self.assertRaises(p.ProvisioningError):
            self.setup_device()
        self.assertFalse(any("install" in cmd for cmd in self.fake.calls))

    def test_policy_and_actual_lock_task_required(self):
        self.fake.locked = True
        valid = self.fake.activities()
        invalid = (
            valid.replace("LOCKED", "PINNED"), valid.replace("LOCKED", "NONE"),
            valid.replace("u0:0", "u0:16"), valid.replace("u0:[", "u10:["),
            valid.replace("com.android.chrome, ", ""),
            valid.replace("com.android.chrome, ", "com.android.chrome.evil, "),
            valid.replace("u0:[", "u0:[com.vendor.unexpected, "),
            valid.replace("10000:" + p.PACKAGE, "10000:com.vendor.other"),
            valid.replace("topResumedActivity=", "unrecognized="),
        )
        p.verify_lock_task(valid)
        for dump in invalid:
            with self.subTest(dump=dump), self.assertRaises(p.ProvisioningError):
                p.verify_lock_task(dump)

    def test_lock_task_missing_never_reports_completion(self):
        self.fake.start_locked = False
        messages = []
        with self.assertRaises(p.ProvisioningError):
            p.setup(self.client.select(), self.apk, self.state, messages.append)
        self.assertFalse(any(text.startswith("Setup verified") for text in messages))

    def test_required_configuration_is_effective_for_user_zero(self):
        valid = "Users:\n  UserInfo{0:Owner:c13}\n    Effective restrictions:\n" + "".join(
            f"      {restriction}\n" for restriction in p.RESTRICTIONS
        ) + "    Other details:\n"
        p.verify_restrictions(valid)
        for output in (
            "", valid.replace("{0:", "{10:"),
            valid.replace("no_safe_boot", "no_safe_boot=false"),
            valid.replace("Effective restrictions:", "Base restrictions:"),
            valid.replace("      no_safe_boot\n", "") + "  UserInfo{10:Other:0}\n    Effective restrictions:\n      no_safe_boot\n",
        ):
            with self.subTest(output=output), self.assertRaises(p.ProvisioningError):
                p.verify_restrictions(output)

    def test_disconnect_during_final_read_stops_immediately(self):
        self.fake.fail = "dumpsys activity activities"
        with self.assertRaises(p.ProvisioningError):
            self.setup_device()
        reads = [cmd for cmd in self.fake.calls if cmd[-3:] == ["dumpsys", "activity", "activities"]]
        self.assertEqual(len(reads), 1)

    def test_disabled_package_noop_is_failure_even_with_zero_exit(self):
        original = self.fake.__call__

        def runner(arguments, timeout=30):
            if "disable-user" in arguments:
                self.fake.calls.append(arguments)
                return "Package unchanged", "", 0
            return original(arguments, timeout)

        self.client.runner = runner
        with self.assertRaises(p.ProvisioningError):
            self.setup_device()
        self.assertFalse(any("set-home-activity" in cmd for cmd in self.fake.calls))

    def test_missing_apk_never_mutates_device(self):
        with self.assertRaises(p.ProvisioningError):
            p.setup(self.client.select(), self.apk.parent / "missing.apk", self.state)
        self.assertEqual(len(self.fake.calls), 1)

    def test_cli_failure_and_success_status(self):
        args = ["setup", "--serial", "TABLET-1", "--apk", str(self.apk), "--state", str(self.state)]
        self.fake.rows = "List of devices attached\n"
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(p.main(args, self.fake, out, err), 1)
        self.assertNotIn("completed", out.getvalue())
        self.assertIn("failed", err.getvalue())
        self.fake.rows = "List of devices attached\nTABLET-1 device\n"
        self.assertEqual(p.main(args, self.fake, io.StringIO(), io.StringIO()), 0)

    def test_restore_and_exit_remain_serial_bound(self):
        self.setup_device()
        args = ["restore", "--serial", "TABLET-1", "--state", str(self.state)]
        self.assertEqual(p.main(args, self.fake, io.StringIO(), io.StringIO()), 0)
        self.assertFalse(self.fake.disabled)
        self.assertEqual(p.main(["exit", "--serial", "TABLET-1"], self.fake, io.StringIO(), io.StringIO()), 0)

    def test_timeout_and_os_error_are_explicit(self):
        with patch.object(p.subprocess, "run", side_effect=subprocess.TimeoutExpired("adb", 1)):
            self.assertNotEqual(p.run_command(["adb"])[2], 0)
        with patch.object(p.subprocess, "run", side_effect=OSError("missing adb")):
            self.assertNotEqual(p.run_command(["adb"])[2], 0)
        with patch.object(p.subprocess, "run", return_value=Mock(stdout="", stderr="", returncode=0)) as run:
            p.run_command(["C:/ADB tools/adb.exe", "devices"])
            self.assertFalse(run.call_args.kwargs["shell"])

    def test_owner_parsing_is_exact_and_user_scoped(self):
        self.assertIsNone(p.owner_component(self.fake.policy()))
        self.fake.owner = p.ADMIN
        self.assertEqual(p.owner_component(self.fake.policy()), p.component_name(p.ADMIN))
        for output in ("", "already owned", self.fake.policy().replace("User ID: 0", "User ID: 10")):
            with self.assertRaises(p.ProvisioningError):
                p.owner_component(output)

    @unittest.skipUnless(os.name == "nt", "Windows batch wrappers")
    def test_batch_wrappers_propagate_failure_without_device_access(self):
        for filename in ("setup-kiosk.bat", "exit-kiosk.bat"):
            result = subprocess.run(
                [os.environ["COMSPEC"], "/d", "/c", str(ROOT / filename),
                 "--adb", str(Path(self.temp.name) / "missing adb.exe"), "--serial", "TABLET-1"],
                capture_output=True, text=True, cwd=ROOT, timeout=30,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertNotIn("completed", result.stdout.lower())
            self.assertIn("discovery failed", result.stderr)


class GuiOperationTests(unittest.TestCase):
    def manager(self):
        manager = gui.KioskManager.__new__(gui.KioskManager)
        manager._events = queue.Queue()
        manager._busy = False
        manager.root = Mock()
        manager.log = Mock()
        manager.device_var = Mock(get=lambda: "TABLET-1")
        manager.client = Mock()
        manager.client.select.return_value = Mock(serial="TABLET-1")
        manager.set_status = Mock()
        return manager

    def test_setup_failure_queues_error_and_never_success(self):
        manager = self.manager()
        with patch.object(gui.provisioning, "setup", side_effect=p.ProvisioningError("install failed")), \
                patch.object(gui.messagebox, "showinfo") as info, \
                patch.object(gui.messagebox, "showerror") as error:
            with patch.object(gui.threading, "Thread") as thread:
                manager.setup_kiosk()
                thread.call_args.kwargs["target"]()
            info.assert_not_called()
            error.assert_not_called()
            manager._drain_events()
            info.assert_not_called()
            error.assert_called_once()
            self.assertFalse(manager._busy)

    def test_no_overlapping_operations(self):
        manager = self.manager()
        with patch.object(gui.threading, "Thread") as thread:
            manager.setup_kiosk()
            manager.setup_kiosk()
            manager.exit_kiosk()
            thread.assert_called_once()

    def test_worker_logs_only_touch_tk_on_main_loop(self):
        manager = self.manager()
        worker = threading.Thread(target=manager.log_add, args=("synthetic log",))
        worker.start()
        worker.join()
        manager.log.insert.assert_not_called()
        manager._drain_events()
        manager.log.insert.assert_called_once_with("end", "synthetic log\n")


if __name__ == "__main__":
    unittest.main()
