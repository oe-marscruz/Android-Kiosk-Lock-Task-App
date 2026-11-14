"""Serial-bound kiosk provisioning shared by the GUI and command line."""

import argparse
from dataclasses import dataclass
from pathlib import Path
import os
import re
import shlex
import subprocess
import sys
import time

import package_policy


PACKAGE = "com.example.webkiosk"
ADMIN = PACKAGE + "/.KioskDeviceAdminReceiver"
HOME = PACKAGE + "/com.example.kiosklauncher.LauncherActivity"
LOCK_PACKAGES = {PACKAGE, "com.android.chrome", "com.android.settings"}
RESTRICTIONS = {"no_safe_boot", "no_factory_reset", "no_usb_file_transfer"}
_COMPONENT = r"[\w.]+/[\w.$]+"


class ProvisioningError(RuntimeError):
    """A required command or verified device state failed."""


@dataclass(frozen=True)
class DeviceRow:
    serial: str
    state: str
    detail: str = ""


def run_command(arguments, timeout=30):
    try:
        result = subprocess.run(
            arguments, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out; device state is unconfirmed.", 1
    except OSError as exc:
        return "", str(exc), 1


def parse_devices(output):
    rows = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith(("List of devices attached", "* daemon", "adb server")):
            continue
        fields = line.split(None, 2)
        if len(fields) < 2 or fields[0].startswith("-"):
            raise ProvisioningError("Unrecognized ADB device list; refresh the connection.")
        rows.append(DeviceRow(fields[0], fields[1], fields[2] if len(fields) > 2 else ""))
    if len({row.serial for row in rows}) != len(rows):
        raise ProvisioningError("Duplicate ADB serials; cannot safely select a tablet.")
    return rows


def select_device(rows, serial=None):
    if serial:
        matches = [row for row in rows if row.serial == serial]
        if len(matches) != 1 or matches[0].state != "device":
            raise ProvisioningError(f"Selected tablet {serial} is missing, offline or unauthorized.")
        return serial
    ready = [row for row in rows if row.state == "device"]
    if not ready:
        raise ProvisioningError("No authorized tablet. Connect USB and accept its debugging prompt.")
    if len(ready) != 1:
        raise ProvisioningError("Multiple authorized tablets. Select an explicit serial first.")
    return ready[0].serial


def component_name(value):
    package, name = value.split("/", 1)
    return package + "/" + (package + name if name.startswith(".") else name)


def owner_component(output):
    if not re.search(r"Device Policy Manager|Device Owner:", output, re.I):
        raise ProvisioningError("Could not parse device-owner state.")
    blocks = re.findall(r"(?mi)^\s*Device Owner:\s*\n((?:[ \t]+[^\n]*\n?)+)", output)
    if not blocks:
        if re.search(r"Device Owner:", output):
            raise ProvisioningError("Unrecognized device-owner record.")
        return None
    if len(blocks) != 1:
        raise ProvisioningError("Ambiguous device-owner records.")
    match = re.search(r"admin=ComponentInfo\{(" + _COMPONENT + r")\}", blocks[0])
    user = re.search(r"User ID:\s*(\d+)", blocks[0])
    if not match or not user or user[1] != "0":
        raise ProvisioningError("Device owner could not be verified for user 0.")
    return component_name(match[1])


class AdbClient:
    def __init__(self, executable, runner=run_command):
        self.executable = str(executable)
        self.runner = runner

    def devices(self):
        out, err, rc = self.runner([self.executable, "devices", "-l"], timeout=30)
        if rc:
            raise ProvisioningError("ADB device discovery failed: " + (err or out).strip())
        return parse_devices(out)

    def select(self, serial=None):
        return Device(self, select_device(self.devices(), serial))


class Device:
    def __init__(self, client, serial):
        self.client = client
        self.serial = serial

    def run(self, arguments, timeout=30):
        # The package-policy module accepts simple command strings. Tokenize
        # those at this boundary; never pass them to a host shell.
        if isinstance(arguments, str):
            arguments = shlex.split(arguments)
        out, err, rc = self.client.runner(
            [self.client.executable, "-s", self.serial, *arguments], timeout=timeout,
        )
        if rc or re.search(r"(?mi)^\s*(?:error:|failure\b|exception\b|java\.[\w.]*Exception)", out + "\n" + err):
            detail = (err or out).strip() or f"exit code {rc}"
            if "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in out + err:
                detail = "Signing mismatch. Follow SIGNING.md migration; no uninstall was attempted."
            raise ProvisioningError(f"{self.serial}: {' '.join(arguments[:4])}: {detail}")
        return out, err, rc

    def output(self, arguments, timeout=30):
        return self.run(arguments, timeout)[0]

    def require_primary_user(self):
        if self.output(["shell", "am", "get-current-user"]).strip() != "0":
            raise ProvisioningError("Setup supports only foreground Android user 0.")


def protected_packages(device):
    packages = set()
    for setting in ("default_input_method", "enabled_accessibility_services"):
        packages.update(package_policy.component_packages(device.output(
            ["shell", "settings", "get", "secure", setting],
        )))
    return packages


def verify_required_packages(device):
    for package in sorted(package_policy.REQUIRED_PACKAGES):
        dump = device.output(["shell", "dumpsys", "package", package])
        user = re.search(r"(?m)^\s*User 0:\s*(.*)$", dump)
        if not user or not all(re.search(pattern, user[1]) for pattern in (
            r"\binstalled=true\b", r"\bhidden=false\b", r"\bsuspended=false\b",
            r"\benabled=[01](?:\s|$)",
        )):
            raise ProvisioningError(f"Required package {package} is absent, disabled, hidden or suspended.")


def verify_owner(device):
    if owner_component(device.output(["shell", "dumpsys", "device_policy"])) != component_name(ADMIN):
        raise ProvisioningError("The exact kiosk receiver is not device owner for user 0.")


def verify_home(device):
    output = device.output([
        "shell", "cmd", "package", "resolve-activity", "--brief", "--user", "0",
        "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME",
    ])
    components = re.findall(r"(?m)^\s*(" + _COMPONENT + r")\s*$", output)
    if len(components) != 1 or component_name(components[0]) != HOME:
        raise ProvisioningError("The kiosk launcher is not the resolved Home activity for user 0.")


def verify_lock_task(output):
    packages = re.search(
        r"mLockTaskPackages \(userId:packages\)=\s*\n((?:[ \t]+u\d+:\[[^\n]*\]\s*\n?)+)", output,
    )
    user = re.search(r"(?m)^\s*u0:\[([^\]]*)\]", packages[1]) if packages else None
    allowed = {value.strip() for value in user[1].split(",")} if user else set()
    if allowed != LOCK_PACKAGES:
        raise ProvisioningError("User 0 lock-task packages are missing, unexpected or unrecognized.")
    features = re.search(
        r"mLockTaskFeatures \(userId:flags\)=\s*\n((?:[ \t]+u\d+:[^\n]+\n?)+)", output,
    )
    if not features or not re.search(r"(?m)^\s*u0:0\s*$", features[1]):
        raise ProvisioningError("User 0 lock-task features are not verified as disabled.")
    if not re.search(r"\bmLockTaskModeState=LOCKED\b", output):
        raise ProvisioningError("Managed lock task is not active (screen pinning does not qualify).")
    tasks = re.search(r"mLockTaskModeTasks=\s*\n(.*?)(?=\n\s*mLockTaskPackages|\Z)", output, re.S)
    if not tasks or not re.search(r"\b" + re.escape(PACKAGE) + r"(?:/|\s|\})", tasks[1]):
        raise ProvisioningError("The kiosk package was not found in active locked tasks.")
    if not re.search(r"(?:topResumedActivity|mResumedActivity)[^\n]*" + re.escape(HOME), output):
        raise ProvisioningError("The kiosk Home activity is not resumed; unlock the test tablet and retry.")


def verify_restrictions(output):
    user = re.search(r"(?m)^[ \t]*UserInfo\{0:[^\n]*\n", output)
    if not user:
        raise ProvisioningError("User 0 restrictions could not be inspected.")
    block = re.split(r"(?m)^[ \t]*UserInfo\{\d+:", output[user.end():], maxsplit=1)[0]
    effective = re.search(r"(?m)^([ \t]*)Effective restrictions:[ \t]*$", block)
    enabled = set()
    if effective:
        indentation = len(effective[1])
        for line in block[effective.end():].splitlines():
            if not line.strip():
                continue
            if len(line) - len(line.lstrip()) <= indentation:
                break
            match = re.fullmatch(r"\s*(no_[a-z_]+)(?:=true)?\s*", line)
            if match:
                enabled.add(match[1])
    if not RESTRICTIONS <= enabled:
        raise ProvisioningError("Required user restrictions are missing or unrecognized: " + ", ".join(sorted(RESTRICTIONS - enabled)))


def verify_setup(device):
    device.require_primary_user()
    verify_owner(device)
    verify_home(device)
    verify_required_packages(device)
    verify_restrictions(device.output(["shell", "dumpsys", "user"]))
    verify_lock_task(device.output(["shell", "dumpsys", "activity", "activities"]))


def setup(device, apk, state_path, log=lambda message: None):
    if not apk or not Path(apk).is_file():
        raise ProvisioningError("APK missing. Provide a reviewed APK with --apk or KIOSK_RELEASE_APK.")
    log(f"Selected tablet: {device.serial}")
    device.require_primary_user()
    owner = owner_component(device.output(["shell", "dumpsys", "device_policy"]))
    if owner is not None and owner != component_name(ADMIN):
        raise ProvisioningError(f"Another device owner is installed: {owner}. No migration or wipe attempted.")

    log("[1/5] Installing the selected APK...")
    out = device.output(["install", "-r", str(Path(apk).resolve())], timeout=120)
    if not re.search(r"(?m)^Success\s*$", out):
        raise ProvisioningError("Install did not confirm success; setup stopped.")

    log("[2/5] Verifying device ownership...")
    if owner is None:
        device.run(["shell", "dpm", "set-device-owner", "--user", "0", ADMIN])
    verify_owner(device)
    verify_required_packages(device)

    log("[3/5] Applying the reviewed optional-package policy...")
    launchers = device.output([
        "shell", "pm", "query-activities", "--brief", "--user", "0",
        "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER",
    ])
    result = package_policy.apply_package_policy(
        device.run, state_path, device.serial, package_policy.launcher_packages(launchers),
        protected_packages=protected_packages(device),
    )
    if result.failures:
        raise ProvisioningError("Package changes failed verification: " + ", ".join(result.failures))
    verify_required_packages(device)

    log("[4/5] Setting Home and applying device-owner policy...")
    device.run(["shell", "cmd", "package", "set-home-activity", "--user", "0", HOME])
    verify_home(device)
    device.run(["shell", "am", "start", "-W", "--user", "0", "-n", HOME])

    log("[5/5] Verifying owner, Home, packages and active managed lock task...")
    # Policy application/startLockTask cross Binder asynchronously. Only reread
    # state during this bounded wait; never repeat installation or enrollment.
    for attempt in range(5):
        activity_state = device.output(["shell", "dumpsys", "activity", "activities"])
        try:
            verify_lock_task(activity_state)
            break
        except ProvisioningError:
            if attempt == 4:
                raise
            time.sleep(0.5)
    verify_setup(device)
    log(f"Setup verified on {device.serial}.")


def exit_kiosk(device):
    device.run(["shell", "am", "force-stop", "--user", "0", PACKAGE])
    output = device.output(["shell", "dumpsys", "activity", "activities"])
    if not re.search(r"\bmLockTaskModeState=NONE\b", output):
        raise ProvisioningError("Stop requested, but exit from lock task is unconfirmed. Device-owner policy remains installed.")


def main(argv=None, runner=run_command, stdout=None, stderr=None):
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("devices", "setup", "verify", "exit", "restore"))
    parser.add_argument("--adb", default=str(Path(__file__).parent / "platform-tools" / ("adb.exe" if sys.platform == "win32" else "adb")))
    parser.add_argument("--serial")
    parser.add_argument("--apk", default=os.environ.get("KIOSK_RELEASE_APK"))
    parser.add_argument("--state", default=str(package_policy.default_state_path()))
    args = parser.parse_args(argv)
    client = AdbClient(args.adb, runner)
    try:
        if args.action == "devices":
            for row in client.devices():
                print(f"{row.serial}\t{row.state}\t{row.detail}", file=stdout)
            return 0
        device = client.select(args.serial)
        if args.action == "setup":
            setup(device, args.apk, args.state, lambda text: print(text, file=stdout))
        elif args.action == "verify":
            verify_setup(device)
        elif args.action == "exit":
            exit_kiosk(device)
        else:
            device.require_primary_user()
            result = package_policy.restore_package_policy(device.run, args.state, device.serial)
            if result.failures:
                raise ProvisioningError("Restoration failed: " + ", ".join(result.failures))
        print(f"{args.action} completed on {device.serial}.", file=stdout)
        return 0
    except (ProvisioningError, package_policy.PackagePolicyError, OSError) as exc:
        print(f"{args.action} failed: {exc}\nSetup may be partial; inspect the selected device before retrying.", file=stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
