"""Safe, repeatable package changes for kiosk provisioning."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
import tempfile


STATE_VERSION = 1

REQUIRED_PACKAGES = frozenset({
    "com.example.webkiosk",
    "com.android.chrome",
    "com.android.settings",
    "com.google.android.deskclock",
})

# Keep this list deliberately small. Packages outside this reviewed set are
# preserved even when they expose a launcher activity.
REVIEWED_OPTIONAL_PACKAGES = frozenset({
    "com.google.android.youtube",
    "com.google.android.apps.youtube.music",
})

_PACKAGE_PATTERN = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$")
_COMPONENT_PATTERN = re.compile(
    r"([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)/[A-Za-z0-9_.$]+"
)


class PackagePolicyError(RuntimeError):
    """Raised when package state cannot be determined safely."""


@dataclass(frozen=True)
class PolicyResult:
    changed: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()


def default_state_path() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return root / "CU-Denver-Equity-Kiosk" / "package-state.json"


def launcher_packages(output: str) -> set[str]:
    packages = set()
    for line in output.splitlines():
        component = line.strip().split()[-1] if line.strip() else ""
        package = component.split("/", 1)[0]
        if _PACKAGE_PATTERN.fullmatch(package):
            packages.add(package)
    return packages


def component_packages(output: str) -> set[str]:
    return set(_COMPONENT_PATTERN.findall(output or ""))


def _disabled_packages(adb_runner) -> set[str]:
    out, err, rc = adb_runner("shell pm list packages -d --user 0")
    if rc != 0:
        detail = (err or out).strip() or "unknown ADB error"
        raise PackagePolicyError(f"Could not read disabled package state: {detail}")
    return {
        line[len("package:"):].strip()
        for line in out.splitlines()
        if line.startswith("package:")
        and _PACKAGE_PATTERN.fullmatch(line[len("package:"):].strip())
    }


def _empty_state() -> dict:
    return {"version": STATE_VERSION, "devices": {}}


def _load_state(path: Path) -> dict:
    if not path.exists():
        return _empty_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackagePolicyError(f"Could not read package state: {exc}") from exc
    if state.get("version") != STATE_VERSION or not isinstance(state.get("devices"), dict):
        raise PackagePolicyError("Package state has an unsupported format")
    return state


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as temporary:
            json.dump(state, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    except OSError as exc:
        raise PackagePolicyError(f"Could not save package state: {exc}") from exc
    finally:
        if temporary_name and os.path.exists(temporary_name):
            try:
                os.unlink(temporary_name)
            except OSError:
                pass


def _device_packages(state: dict, device_id: str, create: bool = False) -> dict:
    if not device_id or device_id in {"unknown", "null"}:
        raise PackagePolicyError("A stable device serial is required for package changes")
    devices = state["devices"]
    if create:
        device = devices.setdefault(device_id, {"packages": {}})
    else:
        device = devices.get(device_id, {"packages": {}})
    packages = device.get("packages")
    if not isinstance(packages, dict):
        raise PackagePolicyError("Package state has an invalid device record")
    return packages


def _remove_empty_device(state: dict, device_id: str) -> None:
    device = state["devices"].get(device_id)
    if device is not None and not device.get("packages"):
        del state["devices"][device_id]


def apply_package_policy(
    adb_runner,
    state_path,
    device_id: str,
    discovered_launcher_packages,
    protected_packages=(),
    reviewed_optional_packages=REVIEWED_OPTIONAL_PACKAGES,
) -> PolicyResult:
    path = Path(state_path)
    state = _load_state(path)
    recorded = _device_packages(state, device_id, create=True)
    disabled = _disabled_packages(adb_runner)
    protected = set(protected_packages) | set(REQUIRED_PACKAGES)
    candidates = sorted(
        (set(discovered_launcher_packages) & set(reviewed_optional_packages)) - protected
    )
    changed = []
    failures = []

    for package in candidates:
        if package in disabled:
            continue

        if package not in recorded:
            recorded[package] = "enabled"
            _save_state(path, state)

        adb_runner(f"shell pm disable-user --user 0 {package}")
        try:
            disabled = _disabled_packages(adb_runner)
        except PackagePolicyError:
            failures.append(package)
            continue

        if package in disabled:
            changed.append(package)
        else:
            failures.append(package)
            recorded.pop(package, None)
            _remove_empty_device(state, device_id)
            _save_state(path, state)

    return PolicyResult(tuple(changed), tuple(failures))


def restore_package_policy(adb_runner, state_path, device_id: str) -> PolicyResult:
    path = Path(state_path)
    state = _load_state(path)
    recorded = _device_packages(state, device_id)
    if not recorded:
        return PolicyResult()

    disabled = _disabled_packages(adb_runner)
    changed = []
    failures = []
    state_changed = False

    for package, original_state in sorted(tuple(recorded.items())):
        if original_state != "enabled":
            raise PackagePolicyError(
                f"Unsupported original state for {package}: {original_state}"
            )
        if package not in disabled:
            recorded.pop(package, None)
            state_changed = True
            continue

        adb_runner(f"shell pm enable --user 0 {package}")
        try:
            disabled = _disabled_packages(adb_runner)
        except PackagePolicyError:
            failures.append(package)
            continue

        if package not in disabled:
            changed.append(package)
            recorded.pop(package, None)
            state_changed = True
        else:
            failures.append(package)

    if state_changed:
        _remove_empty_device(state, device_id)
        _save_state(path, state)

    return PolicyResult(tuple(changed), tuple(failures))
