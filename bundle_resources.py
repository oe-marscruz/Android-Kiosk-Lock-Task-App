"""Resource paths shared by the GUI and the relocated frozen-app check."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import zipfile


def resource_paths():
    frozen = getattr(sys, "frozen", False)
    root = Path(sys._MEIPASS) if frozen else Path(__file__).resolve().parent
    adb = root / "platform-tools" / ("adb.exe" if sys.platform == "win32" else "adb")
    apk = str(root / "CU-Denver-Equity-Kiosk.apk") if frozen else os.environ.get("KIOSK_RELEASE_APK", "")
    return str(root), str(adb), apk


def check_bundle(expected_sha256):
    if not getattr(sys, "frozen", False):
        raise ValueError("Bundle verification requires the frozen application")
    root, adb, apk = resource_paths()
    container = Path(root)
    # PyInstaller links macOS data from Contents/Frameworks into Contents/Resources.
    if (sys.platform == "darwin" and container.name == "Frameworks"
            and container.parent.name == "Contents" and container.parent.parent.suffix == ".app"):
        container = container.parent
    for filename in (adb, apk):
        if not Path(filename).is_file() or not Path(filename).stat().st_size:
            raise ValueError("Missing or empty bundled resource: " + filename)
        if not Path(filename).resolve().is_relative_to(container.resolve()):
            raise ValueError("Resource resolves outside the frozen bundle: " + filename)
    digest = hashlib.sha256(Path(apk).read_bytes()).hexdigest()
    if digest != expected_sha256.lower():
        raise ValueError("Bundled APK SHA-256 differs from the verified packaging input")
    with zipfile.ZipFile(apk) as archive:
        if archive.testzip() is not None or not {"AndroidManifest.xml", "classes.dex"}.issubset(archive.namelist()):
            raise ValueError("Bundled APK is incomplete or corrupt")
    # 'version' executes the binary without starting a server or accessing a tablet.
    result = subprocess.run([adb, "version"], capture_output=True, text=True, timeout=15, check=True)
    if "Android Debug Bridge version " not in result.stdout:
        raise ValueError("Bundled ADB did not report its version")
    return {"status": "PASS", "resource_root": root, "apk_sha256": digest,
            "adb_version": result.stdout.strip(), "platform": platform.platform(),
            "architecture": platform.machine(), "python": platform.python_version(), "frozen": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check frozen resources without opening the GUI or contacting a device")
    parser.add_argument("--expected-apk-sha256", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    try:
        report = check_bundle(args.expected_apk_sha256)
    except (ValueError, OSError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        report = {"status": "FAIL", "error": str(exc)}
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1
