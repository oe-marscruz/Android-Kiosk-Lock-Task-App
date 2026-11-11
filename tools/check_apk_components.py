import argparse
import re
import struct
import subprocess
import sys
import zipfile

EXPECTED_HOME = "com.example.kiosklauncher.LauncherActivity"
EXPECTED_ADMIN = "com.example.webkiosk.KioskDeviceAdminReceiver"


def resolve_name(package, name):
    if name.startswith("."):
        return package + name
    if "." not in name:
        return package + "." + name
    return name


def manifest_components(xmltree):
    package_match = re.search(r'^\s*A: package="([^"]+)"', xmltree, re.M)
    if not package_match:
        raise ValueError("Manifest package not found")
    package = package_match.group(1)
    components = []
    current = None
    for line in xmltree.splitlines():
        element = re.match(r'^(\s*)E: (\S+)', line)
        if element:
            indent, tag = len(element.group(1)), element.group(2)
            if current and indent <= current["indent"]:
                components.append(current)
                current = None
            if tag in ("activity", "receiver"):
                current = {"indent": indent, "tag": tag, "name": None, "home": False}
            continue
        attr = re.match(r'^\s*A: .*:name\([^)]*\)="([^"]+)"', line)
        if current and attr:
            value = attr.group(1)
            if not current["name"]:
                current["name"] = resolve_name(package, value)
            if value == "android.intent.category.HOME":
                current["home"] = True
    if current:
        components.append(current)
    if any(not c["name"] for c in components):
        raise ValueError("Component has no readable name")
    return components


def dex_classes(data):
    if len(data) < 112 or not data.startswith(b"dex\n"):
        raise ValueError("Invalid DEX header")
    def u32(offset):
        if offset < 0 or offset + 4 > len(data):
            raise ValueError("DEX offset outside file")
        return struct.unpack_from("<I", data, offset)[0]
    strings_count, strings_off = u32(56), u32(60)
    types_count, types_off = u32(64), u32(68)
    classes_count, classes_off = u32(96), u32(100)
    result = set()
    for i in range(classes_count):
        type_idx = u32(classes_off + i * 32)
        if type_idx >= types_count:
            raise ValueError("Invalid class type index")
        string_idx = u32(types_off + type_idx * 4)
        if string_idx >= strings_count:
            raise ValueError("Invalid descriptor index")
        offset = u32(strings_off + string_idx * 4)
        # Skip the ULEB128 UTF-16 length; descriptors are ASCII.
        for _ in range(5):
            if offset >= len(data):
                raise ValueError("Truncated descriptor")
            byte = data[offset]
            offset += 1
            if not byte & 0x80:
                break
        else:
            raise ValueError("Invalid string length")
        end = data.find(b"\0", offset)
        if end < 0:
            raise ValueError("Unterminated descriptor")
        descriptor = data[offset:end].decode("ascii")
        if not descriptor.startswith("L") or not descriptor.endswith(";"):
            raise ValueError("Invalid class descriptor")
        result.add(descriptor[1:-1].replace("/", "."))
    return result


def check(apk, aapt2):
    manifest = subprocess.run(
        [aapt2, "dump", "xmltree", "--file", "AndroidManifest.xml", apk],
        check=True, capture_output=True, text=True
    ).stdout
    components = manifest_components(manifest)
    with zipfile.ZipFile(apk) as archive:
        dex_files = [n for n in archive.namelist()
                     if re.fullmatch(r"classes(?:[2-9]|[1-9][0-9]+)?\.dex", n)]
        if not dex_files:
            raise ValueError("No DEX files in APK")
        classes = set()
        for name in dex_files:
            classes.update(dex_classes(archive.read(name)))
    missing = [c["name"] for c in components if c["name"] not in classes]
    homes = [c["name"] for c in components if c["tag"] == "activity" and c["home"]]
    receivers = [c["name"] for c in components if c["tag"] == "receiver"]
    if EXPECTED_HOME not in homes:
        missing.append("expected HOME declaration: " + EXPECTED_HOME)
    if EXPECTED_ADMIN not in receivers:
        missing.append("expected receiver declaration: " + EXPECTED_ADMIN)
    if missing:
        raise ValueError("Component check failed: " + ", ".join(missing))
    print("Verified APK component classes: " + ", ".join(c["name"] for c in components))


def main():
    parser = argparse.ArgumentParser(description="Verify manifest activity and receiver classes in an APK")
    parser.add_argument("apk")
    parser.add_argument("--aapt2", required=True)
    args = parser.parse_args()
    try:
        check(args.apk, args.aapt2)
    except (ValueError, OSError, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())