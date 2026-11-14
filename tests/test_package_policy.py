import json
import pathlib
import tempfile
import unittest

import package_policy


class FakeAdb:
    def __init__(self, disabled=(), fail_disable=(), fail_enable=()):
        self.disabled = set(disabled)
        self.fail_disable = set(fail_disable)
        self.fail_enable = set(fail_enable)
        self.commands = []

    def __call__(self, command):
        self.commands.append(command)
        if command == "shell pm list packages -d --user 0":
            output = "".join(f"package:{name}\n" for name in sorted(self.disabled))
            return output, "", 0

        disable_prefix = "shell pm disable-user --user 0 "
        if command.startswith(disable_prefix):
            package = command[len(disable_prefix):]
            if package in self.fail_disable:
                return "", "disable rejected", 1
            self.disabled.add(package)
            return f"Package {package} new state: disabled-user\n", "", 0

        enable_prefix = "shell pm enable --user 0 "
        if command.startswith(enable_prefix):
            package = command[len(enable_prefix):]
            if package in self.fail_enable:
                return "", "enable rejected", 1
            self.disabled.discard(package)
            return f"Package {package} new state: enabled\n", "", 0

        raise AssertionError(f"Unexpected ADB command: {command}")


class PackagePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_path = pathlib.Path(self.temp_dir.name) / "package-state.json"

    def test_only_reviewed_optional_packages_are_disabled(self):
        launcher_output = "\n".join([
            "com.example.webkiosk/.MainActivity",
            "com.android.chrome/com.google.android.apps.chrome.Main",
            "com.android.settings/.Settings",
            "com.google.android.deskclock/.DeskClock",
            "com.google.android.inputmethod.latin/.setup.SetupActivity",
            "com.example.accessibility/.SettingsActivity",
            "com.vendor.unknown/.MainActivity",
            "com.google.android.youtube/.HomeActivity",
        ])
        adb = FakeAdb()

        result = package_policy.apply_package_policy(
            adb,
            self.state_path,
            "TABLET-1",
            package_policy.launcher_packages(launcher_output),
            protected_packages={
                "com.google.android.inputmethod.latin",
                "com.example.accessibility",
            },
        )

        self.assertEqual(result.changed, ("com.google.android.youtube",))
        self.assertEqual(result.failures, ())
        self.assertEqual(adb.disabled, {"com.google.android.youtube"})
        disable_commands = [c for c in adb.commands if " disable-user " in c]
        self.assertEqual(disable_commands, [
            "shell pm disable-user --user 0 com.google.android.youtube"
        ])

    def test_setup_twice_then_restore_only_undoes_setup_changes(self):
        unrelated_disabled = "com.vendor.previously.disabled"
        launcher_packages = {
            "com.google.android.youtube",
            "com.google.android.apps.youtube.music",
            unrelated_disabled,
        }
        adb = FakeAdb(disabled={unrelated_disabled})

        first = package_policy.apply_package_policy(
            adb, self.state_path, "TABLET-1", launcher_packages
        )
        saved_after_first = self.state_path.read_text(encoding="utf-8")
        second = package_policy.apply_package_policy(
            adb, self.state_path, "TABLET-1", launcher_packages
        )
        saved_after_second = self.state_path.read_text(encoding="utf-8")

        self.assertEqual(set(first.changed), {
            "com.google.android.youtube",
            "com.google.android.apps.youtube.music",
        })
        self.assertEqual(second.changed, ())
        self.assertEqual(saved_after_second, saved_after_first)

        restored = package_policy.restore_package_policy(
            adb, self.state_path, "TABLET-1"
        )

        self.assertEqual(set(restored.changed), {
            "com.google.android.youtube",
            "com.google.android.apps.youtube.music",
        })
        self.assertEqual(adb.disabled, {unrelated_disabled})
        enable_commands = [c for c in adb.commands if " pm enable " in c]
        self.assertNotIn(
            f"shell pm enable --user 0 {unrelated_disabled}", enable_commands
        )

    def test_first_run_state_is_not_overwritten_by_later_device_state(self):
        package = "com.google.android.youtube"
        adb = FakeAdb()
        package_policy.apply_package_policy(
            adb, self.state_path, "TABLET-1", {package}
        )
        adb.disabled.clear()

        package_policy.apply_package_policy(
            adb, self.state_path, "TABLET-1", {package}
        )

        saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(
            saved["devices"]["TABLET-1"]["packages"],
            {package: "enabled"},
        )

    def test_failed_disable_is_reported_and_not_recorded_as_a_change(self):
        package = "com.google.android.youtube"
        adb = FakeAdb(fail_disable={package})

        result = package_policy.apply_package_policy(
            adb, self.state_path, "TABLET-1", {package}
        )

        self.assertEqual(result.changed, ())
        self.assertEqual(result.failures, (package,))
        saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["devices"], {})

    def test_failed_restore_remains_recorded_for_retry(self):
        package = "com.google.android.youtube"
        adb = FakeAdb()
        package_policy.apply_package_policy(
            adb, self.state_path, "TABLET-1", {package}
        )
        adb.fail_enable.add(package)

        result = package_policy.restore_package_policy(
            adb, self.state_path, "TABLET-1"
        )

        self.assertEqual(result.failures, (package,))
        saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(
            saved["devices"]["TABLET-1"]["packages"],
            {package: "enabled"},
        )

    def test_component_package_parsing_ignores_invalid_values(self):
        output = (
            "com.google.android.inputmethod.latin/.LatinIME\n"
            "com.example.reader/.AccessibilityService:"
            "com.example.other/.Service\n"
            "null\n"
        )

        self.assertEqual(
            package_policy.component_packages(output),
            {
                "com.google.android.inputmethod.latin",
                "com.example.reader",
                "com.example.other",
            },
        )


if __name__ == "__main__":
    unittest.main()
