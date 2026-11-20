#!/usr/bin/env python3
"""Publication gate (ARCHITECTURE.md §7.2, P1b): verify and classify a build candidate.

Stdlib only, except the pinned PyInstaller archive reader used to read the final
EXE / app bundle. Nothing from the candidate is executed: the archive reader only
parses the CArchive table of contents, and APK bytes go to apksigner as data.

Any failed check exits non-zero before outputs are written, so no allow flag is set.
"""
import argparse
import dataclasses
import hashlib
import os
import re
import subprocess
import stat
import struct
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

APK_NAME = "CU-Denver-Equity-Kiosk.apk"
JAVA_SRC = ("app", "src", "main", "java")
CHECKOUT_ANCHORS = ("kiosk-manager.py", "app/src/main/AndroidManifest.xml", "app/src/main/java/com/example/webkiosk")
APK_INFO_KEYS = ("variant", "apk", "apk_sha256", "signer_cert_sha256")
ANDROID_DEBUG_DN = {"CN=Android Debug", "O=Android", "C=US"}
VERSION_TAG = re.compile(r"refs/tags/v[0-9A-Za-z][0-9A-Za-z._+-]*")
SUPPRESSED = "internal upload suppressed: no verified private destination"
DEBUG_WARNING = ("Debug APK, not a fleet release. Each CI run may use a different signing key, so updates to "
                 "existing installations can fail. Do not uninstall or reset to force an update. Inventory the "
                 "installed signer and follow supervised recovery.")


class GateError(Exception):
    pass


# ---------------------------------------------------------------- capability

def parse_remote_flag(value):
    if value not in ("0", "1"):
        raise GateError(f"REMOTE_FEATURES must be exactly 0 or 1, got {value!r}")
    return value == "1"


def load_inventory(path):
    prefixes = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = PurePosixPath(line).parts
        if not line.endswith("/**") or len(parts) < 2 or line.startswith("/") \
                or any(p in ("..", ".") or "*" in p for p in parts[:-1]):
            raise GateError(f"unknown inventory entry {line!r}: expected a relative '<dir>/**' glob")
        prefixes.append(parts[:-1])
    if not prefixes:
        raise GateError(f"inventory {path} is empty")
    return prefixes


def checkout_hits(repo, prefixes):
    repo = Path(repo)
    missing = [a for a in CHECKOUT_ANCHORS if not (repo / a).exists()]
    if missing:
        raise GateError(f"unknown checkout layout: missing {missing}")
    return ["/".join(p) for p in prefixes if (repo / Path(*p)).exists()]


def _contains(parts, prefix):
    n = len(prefix)
    return any(tuple(parts[i:i + n]) == prefix for i in range(len(parts) - n + 1))


def package_hits(entries, dex_blobs, prefixes):
    """entries: archive / filesystem names (paths or dotted module names)."""
    split = [tuple(p for p in re.split(r"[/\\.]", e) if p) for e in entries]
    hits = []
    for prefix in prefixes:
        if prefix[:len(JAVA_SRC)] == JAVA_SRC:
            needle = ("L" + "/".join(prefix[len(JAVA_SRC):]) + "/").encode()
            if any(needle in blob for blob in dex_blobs):
                hits.append("/".join(prefix))
        elif any(_contains(parts, prefix) for parts in split):
            hits.append("/".join(prefix))
    return hits


def capability(remote_flag, hits):
    remote = bool(hits)
    if remote != remote_flag:
        raise GateError(
            f"REMOTE_FEATURES={int(remote_flag)} but inventory hits are {hits or 'none'}: capability mismatch")
    return "remote-capable" if remote else "usb-only"


def dex_blobs(apk_bytes):
    import io
    with zipfile.ZipFile(io.BytesIO(apk_bytes)) as z:
        names = [n for n in z.namelist() if re.fullmatch(r"classes\d*\.dex", n)]
        if names.count("classes.dex") != 1 or len(names) != len(set(names)):
            raise GateError("APK must contain exactly one classes.dex and no duplicate DEX entries")
        blobs = [z.read(n) for n in names]
        if any(not blob.startswith(b"dex\n") for blob in blobs):
            raise GateError("APK contains an invalid DEX magic")
        return blobs


# ---------------------------------------------------------------- APK

def sha256(data):
    return hashlib.sha256(data).hexdigest()


def normalize_fp(value):
    fp = (value or "").replace(":", "").replace(" ", "").lower()
    if fp and not re.fullmatch(r"[0-9a-f]{64}", fp):
        raise GateError(f"KIOSK_CERT_SHA256 is not a SHA-256 fingerprint: {value!r}")
    return fp


def parse_apk_info(path):
    info = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            key, sep, value = line.partition("=")
            if not sep or key in info:
                raise GateError(f"malformed apk-info line {line!r}")
            info[key] = value
    if sorted(info) != sorted(APK_INFO_KEYS) or info["variant"] not in ("debug", "release"):
        raise GateError(f"unknown apk-info.txt layout: {info}")
    return info


def _apksigner_cmd():
    jar = os.environ.get("APKSIGNER_JAR")
    if not jar:
        sdks = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")]
        props = Path(__file__).resolve().parent.parent / "local.properties"
        if props.is_file():
            sdks += [l.split("=", 1)[1] for l in props.read_text().splitlines() if l.startswith("sdk.dir=")]
        jars = [j for s in sdks if s for j in Path(s).glob("build-tools/*/lib/apksigner.jar")]
        if not jars:
            raise GateError("apksigner.jar not found: set APKSIGNER_JAR or ANDROID_HOME")
        version = lambda j: tuple(int(x) if x.isdigit() else -1 for x in re.split(r"[.-]", j.parent.parent.name))
        jar = str(max(jars, key=version))
    java_home = os.environ.get("JAVA_HOME")
    java = str(Path(java_home, "bin", "java")) if java_home else "java"
    return [java, "-jar", jar]


def apksigner_signer(apk_path):
    """Returns (cert SHA-256, DN) of the single signer, via apksigner verify --print-certs."""
    proc = subprocess.run(_apksigner_cmd() + ["verify", "--print-certs", str(apk_path)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise GateError(f"apksigner verify failed for {apk_path}:\n{proc.stdout}{proc.stderr}")
    digests = re.findall(r"^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})$", proc.stdout, re.M)
    dns = re.findall(r"^Signer #\d+ certificate DN: (.*)$", proc.stdout, re.M)
    if len(digests) != 1 or len(dns) != 1:
        raise GateError(f"expected exactly one signer in {apk_path}:\n{proc.stdout}")
    return digests[0].lower(), dns[0].strip()


def classify_apk(info, apk_sha256, signer, signer_dn, approved_fp):
    """apk-info.txt must agree with the independent check. Debug is never relabelled."""
    if info["apk_sha256"].lower() != apk_sha256:
        raise GateError(f"APK SHA-256 {apk_sha256} != apk-info {info['apk_sha256']}")
    if info["signer_cert_sha256"].lower() != signer:
        raise GateError(f"APK signer {signer} != apk-info {info['signer_cert_sha256']}")
    if info["variant"] == "debug":
        return "debug"
    if {p.strip() for p in signer_dn.split(",")} == ANDROID_DEBUG_DN:
        raise GateError("apk-info says release but the APK is signed with an Android debug key")
    if not approved_fp:
        return "release-unpinned"
    if signer != approved_fp:
        raise GateError(f"release APK signer {signer} != KIOSK_CERT_SHA256 {approved_fp}")
    return "release"


def verify_apk_bytes(data, label, expected_sha, expected_signer):
    if sha256(data) != expected_sha:
        raise GateError(f"{label}: SHA-256 {sha256(data)} != verified APK {expected_sha}")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, "embedded.apk")
        path.write_bytes(data)
        signer, _ = apksigner_signer(path)
    if signer != expected_signer:
        raise GateError(f"{label}: signer {signer} != verified APK signer {expected_signer}")


# ---------------------------------------------------------------- packages

def read_pyinstaller(path):
    """(entry names incl. PYZ module names, {entry: bytes} of *.apk entries). Parses only."""
    from PyInstaller.archive.readers import CArchiveReader, pkg_archive_contents
    class CheckedReader(CArchiveReader):
        @classmethod
        def _parse_toc(cls, data):
            seen = set()
            pos = 0
            while pos < len(data):
                if len(data) - pos < cls._TOC_ENTRY_LENGTH:
                    raise GateError("truncated PyInstaller TOC")
                length = struct.unpack_from(cls._TOC_ENTRY_FORMAT, data, pos)[0]
                if length <= cls._TOC_ENTRY_LENGTH or pos + length > len(data):
                    raise GateError("invalid PyInstaller TOC entry length")
                name = data[pos + cls._TOC_ENTRY_LENGTH:pos + length].rstrip(b"\0").decode("utf-8")
                if name in seen:
                    raise GateError(f"duplicate PyInstaller TOC entry: {name}")
                seen.add(name)
                pos += length
            return super()._parse_toc(data)

    reader = CheckedReader(str(path))
    names = pkg_archive_contents(str(path), recursive=True)
    if [n for n in reader.toc if n.lower().endswith(".apk")] != [APK_NAME]:
        raise GateError(f"{path}: expected exactly one embedded {APK_NAME}")
    if not any(entry[4] == "z" for entry in reader.toc.values()):
        raise GateError(f"unknown PyInstaller layout in {path}: no PYZ archive")
    apks = {n: reader.extract(n) for n in reader.toc if n.lower().endswith(".apk")}
    return names, apks


def inspect_exe(exe):
    names, apks = read_pyinstaller(exe)
    if list(apks) != [APK_NAME]:
        raise GateError(f"{exe}: expected exactly one embedded {APK_NAME}, found {sorted(apks)}")
    return names, {f"{Path(exe).name}!{n}": b for n, b in apks.items()}


def inspect_dmg_tree(root):
    """root: the read-only mount of the final DMG."""
    root = Path(root)
    apps = [p for p in root.iterdir() if p.suffix == ".app" and p.is_dir()]
    apk_dir = root / "Kiosk-APK"
    apk_path = apk_dir / APK_NAME
    try:
        valid_apk = stat.S_ISDIR(os.lstat(apk_dir).st_mode) and stat.S_ISREG(os.lstat(apk_path).st_mode)
    except OSError:
        valid_apk = False
    if len(apps) != 1 or not valid_apk:
        raise GateError(f"unknown DMG layout in {root}: need one .app and Kiosk-APK/{APK_NAME}")
    names, apks, archives = [], {}, 0
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath, name)
            rel = path.relative_to(root).as_posix()
            names.append(rel)
            if path.is_symlink() and path.resolve().suffix.lower() == ".apk":
                raise GateError(f"symlink to APK in DMG: {rel}")
            if name.lower().endswith(".apk"):
                if path.is_symlink() or not path.is_file() or path != apk_path:
                    raise GateError(f"unexpected APK entry in DMG: {rel}")
                apks[rel] = path.read_bytes()
    for path in sorted((apps[0] / "Contents" / "MacOS").glob("*")):
        if path.is_symlink() or not path.is_file():
            raise GateError(f"invalid app executable: {path}")
        if path.is_file():
            try:
                inner, embedded = read_pyinstaller(path)
            except Exception as e:
                raise GateError(f"unreadable PyInstaller archive {path}: {e}") from e
            archives += 1
            names += inner
            for n, b in embedded.items():
                if n != APK_NAME:
                    raise GateError(f"unexpected APK entry {n} in {path.name}")
                apks[f"{path.relative_to(root).as_posix()}!{n}"] = b
    if archives == 0:
        raise GateError(f"unknown DMG layout: no PyInstaller executable in {apps[0].name}/Contents/MacOS")
    return names, apks


def exe_signature_class(evidence_path, exe_sha):
    """Authenticode evidence written by the signing step. Only fully proven signatures count."""
    ev = dict(l.split("=", 1) for l in Path(evidence_path).read_text().splitlines() if "=" in l)
    if ev.get("authenticode") == "unsigned" and len(ev) == 1:
        return "unsigned", "EXE is not signed"
    if ev.get("authenticode") != "signed":
        raise GateError(f"unknown authenticode evidence: {ev}")
    if ev.get("exe_sha256", "").lower() != exe_sha:
        raise GateError("authenticode evidence is not bound to the final EXE digest")
    proven = (ev.get("signtool_verify") == "pass" and ev.get("signature_count") == "1"
              and ev.get("signer_thumbprint_match") == "true" and ev.get("rfc3161_validated") == "true")
    if proven:
        return "authenticode-signed", "signature, publisher pin and RFC 3161 token verified"
    return "unsigned", f"EXE signature not release-eligible: {ev}"


# ---------------------------------------------------------------- decision

@dataclasses.dataclass(frozen=True)
class Decision:
    public_release: bool
    internal_upload: bool
    release_ref: str
    reason: str
    pr_artifact: bool = False


def decide(platform, event_name, ref, default_branch, capability, apk_class, exe_class,
           private_destination_verified=False, base_ref=""):
    """Default-deny publication matrix (§7.2), narrowed for P1b: no remote release, no prerelease.

    The one non-push path is the user-approved PR test artifact (§8.2): a debug build
    of a pull request into the default branch, uploaded as an Actions artifact only.
    """
    deny = lambda why: Decision(False, False, "", why)
    if platform not in ("windows", "macos"):
        return deny(f"unknown platform {platform!r}")
    if event_name == "pull_request":
        if not default_branch or base_ref != default_branch:
            return deny(f"pull_request into {base_ref!r} is not into the default branch")
        if capability not in ("usb-only", "remote-capable"):
            return deny(f"unknown capability {capability!r}")
        if apk_class != "debug":
            return deny(f"PR test artifacts are debug-only (APK class {apk_class!r})")
        if platform == "windows" and exe_class != "unsigned":
            return deny(f"PR test artifacts are unsigned-only (EXE class {exe_class!r})")
        return Decision(False, False, "", "PR test artifact (debug, not a fleet release)", pr_artifact=True)
    if event_name != "push":
        return deny(f"event {event_name!r} never publishes")
    is_default = bool(default_branch) and ref == f"refs/heads/{default_branch}"
    is_tag = bool(VERSION_TAG.fullmatch(ref or ""))
    if not (is_default or is_tag):
        return deny(f"ref {ref!r} is neither the default branch nor a v* tag")
    if capability != "usb-only":
        return deny(f"{capability} candidates need remote evidence gates that do not exist yet")
    if apk_class not in ("debug", "release"):
        return deny(f"APK class {apk_class!r} is not eligible (release needs KIOSK_CERT_SHA256)")

    internal = False
    if platform == "windows":
        if is_tag and apk_class == "release" and exe_class == "authenticode-signed":
            return Decision(True, False, ref, "usb-only / release APK / signed EXE on a v* tag")
        internal = is_default and apk_class == "debug" and exe_class == "unsigned"
    else:
        internal = True
    if not internal:
        return deny(f"{platform} {apk_class}/{exe_class} on {ref} has no allowed mutation")
    if not private_destination_verified:
        return deny(SUPPRESSED)
    return Decision(False, True, "", "restricted internal upload")


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--platform", required=True, choices=("windows", "macos"))
    ap.add_argument("--repo", default=".")
    ap.add_argument("--inventory", default="release/remote-inventory.txt")
    ap.add_argument("--apk", default="build/" + APK_NAME)
    ap.add_argument("--apk-info", default="build/apk-info.txt")
    ap.add_argument("--exe", help="final (signed, if signed) Windows EXE")
    ap.add_argument("--authenticode-evidence")
    ap.add_argument("--dmg", help="final DMG (digest only)")
    ap.add_argument("--dmg-mount", help="read-only mount point of the final DMG")
    ap.add_argument("--record", help="write the candidate record here")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    args = ap.parse_args(argv)

    try:
        remote_flag = parse_remote_flag(os.environ.get("REMOTE_FEATURES"))
        prefixes = load_inventory(args.inventory)
        approved = normalize_fp(os.environ.get("KIOSK_CERT_SHA256"))

        apk_bytes = Path(args.apk).read_bytes()
        info = parse_apk_info(args.apk_info)
        apk_sha = sha256(apk_bytes)
        signer, dn = apksigner_signer(args.apk)
        apk_class = classify_apk(info, apk_sha, signer, dn, approved)

        record = {"platform": args.platform, "apk_sha256": apk_sha, "apk_signer_sha256": signer}
        if args.platform == "windows":
            if not (args.exe and args.authenticode_evidence):
                raise GateError("windows needs --exe and --authenticode-evidence")
            exe_sha = sha256(Path(args.exe).read_bytes())
            names, apks = inspect_exe(args.exe)
            exe_class, exe_note = exe_signature_class(args.authenticode_evidence, exe_sha)
            record["exe_sha256"] = exe_sha
        else:
            if not args.dmg_mount:
                raise GateError("macos needs --dmg-mount")
            names, apks = inspect_dmg_tree(args.dmg_mount)
            exe_class, exe_note = "n/a", "macOS has no Authenticode axis"
            if args.dmg:
                record["dmg_sha256"] = sha256(Path(args.dmg).read_bytes())
        for label, data in apks.items():
            verify_apk_bytes(data, label, apk_sha, signer)
        print(f"verified {len(apks)} packaged APK cop{'y' if len(apks) == 1 else 'ies'}: {sorted(apks)}")

        hits = sorted(set(checkout_hits(args.repo, prefixes)) | set(
            package_hits(names, [b for d in [apk_bytes, *apks.values()] for b in dex_blobs(d)], prefixes)))
        cap = capability(remote_flag, hits)
    except (GateError, OSError, zipfile.BadZipFile) as e:
        print(f"::error::publication gate: {e}", file=sys.stderr)
        return 1

    event = os.environ.get("GITHUB_EVENT_NAME", "")
    ref = os.environ.get("GITHUB_REF", "")
    destination_set = bool(os.environ.get("PRIVATE_ARTIFACT_DESTINATION"))
    # No destination verifier exists yet (P1b), so a configured value is still unverified.
    decision = decide(args.platform, event, ref, os.environ.get("DEFAULT_BRANCH", ""), cap, apk_class,
                      exe_class, private_destination_verified=False,
                      base_ref=os.environ.get("GITHUB_BASE_REF", ""))
    label = f"{cap} / {apk_class} APK" + (f" / {exe_class} EXE" if args.platform == "windows" else "")
    commit = os.environ.get("GITHUB_SHA") or subprocess.run(
        ["git", "-C", args.repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    record.update(commit=commit, event=event, ref=ref, capability=cap, apk_class=apk_class,
                  exe_class=exe_class, exe_note=exe_note, inventory_hits=",".join(hits) or "none",
                  private_destination_configured=str(destination_set).lower(),
                  allow_public_release=str(decision.public_release).lower(),
                  allow_internal_upload=str(decision.internal_upload).lower(),
                  allow_pr_artifact=str(decision.pr_artifact).lower(), reason=decision.reason)
    outputs = {"capability": cap, "apk_class": apk_class, "exe_class": exe_class, "label": label,
               "allow_public_release": record["allow_public_release"],
               "allow_internal_upload": record["allow_internal_upload"],
               "allow_pr_artifact": record["allow_pr_artifact"],
               "release_ref": decision.release_ref, "reason": decision.reason}

    print(f"candidate: {label}")
    if apk_class == "debug":
        print(f"::warning::{DEBUG_WARNING}" + (" Unsigned executable." if exe_class == "unsigned" else ""))
    print(f"decision: {decision.reason}")
    if decision.reason == SUPPRESSED:
        print(SUPPRESSED)
    if args.record:
        Path(args.record).write_text("".join(f"{k}={v}\n" for k, v in record.items()))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as out:
            out.writelines(f"{k}={v}\n" for k, v in outputs.items())
    return 0


if __name__ == "__main__":
    sys.exit(main())
