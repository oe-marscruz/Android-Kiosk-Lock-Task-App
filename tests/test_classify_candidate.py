"""Publication gate classifier and decision matrix (ARCHITECTURE.md §7.2, P1b)."""
import importlib.util
import itertools
import pathlib
import tempfile
import unittest

_path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "classify_candidate.py"
_spec = importlib.util.spec_from_file_location("classify_candidate", _path)
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)

INVENTORY = pathlib.Path(__file__).resolve().parent.parent / "release" / "remote-inventory.txt"
SHA = "a" * 64
SIGNER = "b" * 64
OTHER = "c" * 64
DEBUG_DN = "C=US, O=Android, CN=Android Debug"
RELEASE_DN = "CN=CU Denver Equity, O=University of Colorado, C=US"


def write_tmp(case, text, suffix=".txt"):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    path = pathlib.Path(tmp.name, "f" + suffix)
    path.write_text(text)
    return path


def info(variant, apk_sha=SHA, signer=SIGNER):
    return {"variant": variant, "apk": f"app-{variant}.apk", "apk_sha256": apk_sha, "signer_cert_sha256": signer}


class Flag(unittest.TestCase):
    def test_only_exact_0_or_1(self):
        self.assertFalse(cc.parse_remote_flag("0"))
        self.assertTrue(cc.parse_remote_flag("1"))
        for bad in (None, "", "true", "yes", " 1", "01", "2"):
            with self.assertRaises(cc.GateError, msg=repr(bad)):
                cc.parse_remote_flag(bad)


class Inventory(unittest.TestCase):
    def setUp(self):
        self.prefixes = cc.load_inventory(INVENTORY)

    def test_maintained_inventory_lists_all_remote_paths(self):
        self.assertEqual(
            ["/".join(p) for p in self.prefixes],
            ["relay", "kiosk_remote", "app/src/main/java/com/example/webkiosk/remote"])

    def test_unknown_inventory_entry_fails(self):
        for line in ("relay", "relay/*", "/relay/**", "../relay/**", "re*/**"):
            with self.assertRaises(cc.GateError, msg=line):
                cc.load_inventory(write_tmp(self, line + "\n"))

    def _checkout(self, tmp):
        root = pathlib.Path(tmp)
        (root / "app/src/main/java/com/example/webkiosk").mkdir(parents=True)
        (root / "app/src/main/AndroidManifest.xml").write_text("<manifest/>")
        (root / "kiosk-manager.py").write_text("")
        return root

    def test_checkout_mismatch_fails_both_ways(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._checkout(tmp)
            self.assertEqual(cc.capability(False, cc.checkout_hits(root, self.prefixes)), "usb-only")
            with self.assertRaises(cc.GateError):
                cc.capability(True, cc.checkout_hits(root, self.prefixes))
            (root / "app/src/main/java/com/example/webkiosk/remote").mkdir()
            hits = cc.checkout_hits(root, self.prefixes)
            self.assertEqual(cc.capability(True, hits), "remote-capable")
            with self.assertRaises(cc.GateError):
                cc.capability(False, hits)

    def test_unknown_checkout_layout_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(cc.GateError):
                cc.checkout_hits(tmp, self.prefixes)

    def test_package_contents(self):
        usb = ["kiosk-manager", "platform-tools/adb.exe", "CU-Denver-Equity-Kiosk.apk", "tkinter.ttk"]
        self.assertEqual(cc.package_hits(usb, [b"Lcom/example/webkiosk/MainActivity;"], self.prefixes), [])
        self.assertEqual(cc.package_hits(usb + ["kiosk_remote.client"], [], self.prefixes), ["kiosk_remote"])
        self.assertEqual(cc.package_hits(usb + ["App.app/Contents/Resources/relay/x"], [], self.prefixes), ["relay"])
        self.assertEqual(
            cc.package_hits(usb, [b"..Lcom/example/webkiosk/remote/Agent;.."], self.prefixes),
            ["app/src/main/java/com/example/webkiosk/remote"])


class Apk(unittest.TestCase):
    def test_apk_info_must_match_independent_check(self):
        with self.assertRaises(cc.GateError):
            cc.classify_apk(info("debug", apk_sha=OTHER), SHA, SIGNER, DEBUG_DN, "")
        with self.assertRaises(cc.GateError):
            cc.classify_apk(info("debug", signer=OTHER), SHA, SIGNER, DEBUG_DN, "")

    def test_debug_is_never_relabelled_release(self):
        self.assertEqual(cc.classify_apk(info("debug"), SHA, SIGNER, DEBUG_DN, SIGNER), "debug")
        self.assertEqual(cc.classify_apk(info("debug"), SHA, SIGNER, RELEASE_DN, SIGNER), "debug")
        with self.assertRaises(cc.GateError):
            cc.classify_apk(info("release"), SHA, SIGNER, DEBUG_DN, SIGNER)

    def test_release_needs_the_approved_fingerprint(self):
        self.assertEqual(cc.classify_apk(info("release"), SHA, SIGNER, RELEASE_DN, SIGNER), "release")
        self.assertEqual(cc.classify_apk(info("release"), SHA, SIGNER, RELEASE_DN, ""), "release-unpinned")
        with self.assertRaises(cc.GateError):
            cc.classify_apk(info("release"), SHA, SIGNER, RELEASE_DN, OTHER)

    def test_fingerprint_normalisation(self):
        self.assertEqual(cc.normalize_fp(":".join(["AB"] * 32)), "ab" * 32)
        self.assertEqual(cc.normalize_fp(""), "")
        with self.assertRaises(cc.GateError):
            cc.normalize_fp("not-a-fingerprint")

    def test_apk_info_layout(self):
        with self.assertRaises(cc.GateError):
            cc.parse_apk_info(write_tmp(self, "variant=release-ish\napk=x\napk_sha256=1\nsigner_cert_sha256=2\n"))


class Authenticode(unittest.TestCase):
    def evidence(self, text):
        return write_tmp(self, text)

    FULL = "authenticode=signed\nexe_sha256={sha}\nsigntool_verify=pass\nsignature_count=1\n" \
           "signer_thumbprint_match=true\nrfc3161_validated={ts}\n"

    def test_unsigned(self):
        self.assertEqual(cc.exe_signature_class(self.evidence("authenticode=unsigned\n"), SHA)[0], "unsigned")

    def test_signed_without_rfc3161_proof_is_not_eligible(self):
        ev = self.evidence(self.FULL.format(sha=SHA, ts="false"))
        self.assertEqual(cc.exe_signature_class(ev, SHA)[0], "unsigned")

    def test_fully_proven_signature(self):
        ev = self.evidence(self.FULL.format(sha=SHA, ts="true"))
        self.assertEqual(cc.exe_signature_class(ev, SHA)[0], "authenticode-signed")

    def test_evidence_bound_to_digest(self):
        with self.assertRaises(cc.GateError):
            cc.exe_signature_class(self.evidence(self.FULL.format(sha=OTHER, ts="true")), SHA)
        with self.assertRaises(cc.GateError):
            cc.exe_signature_class(self.evidence(""), SHA)


class Decide(unittest.TestCase):
    MAIN = "refs/heads/main"
    TAG = "refs/tags/v1.2.0"

    def d(self, platform="windows", event="push", ref=TAG, cap="usb-only", apk="release",
          exe="authenticode-signed", verified=False):
        return cc.decide(platform, event, ref, "main", cap, apk, exe, verified)

    def test_only_allowed_public_release(self):
        d = self.d()
        self.assertTrue(d.public_release)
        self.assertEqual(d.release_ref, self.TAG)

    def test_full_matrix(self):
        events = ("push", "pull_request", "workflow_dispatch", "schedule", "release")
        refs = (self.MAIN, self.TAG, "refs/heads/master", "refs/heads/feature", "refs/tags/latest",
                "refs/tags/1.0", "refs/tags/v", "refs/pull/1/merge", "")
        caps = ("usb-only", "remote-capable")
        apks = ("debug", "release", "release-unpinned")
        exes = ("unsigned", "authenticode-signed", "n/a")
        public = []
        for case in itertools.product(("windows", "macos"), events, refs, caps, apks, exes, (False, True)):
            platform, event, ref, cap, apk, exe, verified = case
            d = cc.decide(platform, event, ref, "main", cap, apk, exe, verified)
            if d.public_release:
                public.append(case[:-1])
                self.assertEqual(d.release_ref, ref)
            if not verified:
                self.assertFalse(d.internal_upload, case)
            if event != "push" or cap != "usb-only" or apk == "release-unpinned":
                self.assertEqual((d.public_release, d.internal_upload), (False, False), case)
            if d.internal_upload:
                self.assertIn((platform, ref, apk, exe), {
                    ("windows", self.MAIN, "debug", "unsigned"),
                    *(("macos", r, a, exe) for r in (self.MAIN, self.TAG) for a in ("debug", "release"))})
        self.assertEqual(sorted(set(public)), [
            ("windows", "push", self.TAG, "usb-only", "release", "authenticode-signed")])

    def test_denials(self):
        self.assertFalse(self.d(event="pull_request").public_release)
        self.assertFalse(self.d(event="workflow_dispatch").public_release)
        self.assertFalse(self.d(cap="remote-capable").public_release)
        self.assertFalse(self.d(apk="debug").public_release)
        self.assertFalse(self.d(exe="unsigned").public_release)
        self.assertFalse(self.d(ref="refs/tags/latest").public_release)
        self.assertFalse(self.d(ref=self.MAIN).public_release)
        self.assertFalse(self.d(platform="macos").public_release)
        self.assertFalse(cc.decide("windows", "push", self.TAG, "", "usb-only", "debug", "unsigned").public_release)

    def test_internal_upload_suppressed_without_verified_destination(self):
        d = self.d(ref=self.MAIN, apk="debug", exe="unsigned")
        self.assertEqual((d.internal_upload, d.reason), (False, cc.SUPPRESSED))
        self.assertTrue(self.d(ref=self.MAIN, apk="debug", exe="unsigned", verified=True).internal_upload)
        self.assertFalse(self.d(ref=self.MAIN, apk="debug", exe="unsigned", cap="remote-capable",
                                verified=True).internal_upload)

    def test_platforms_are_independent(self):
        mac = self.d(platform="macos", ref=self.MAIN, apk="debug", exe="n/a", verified=True)
        win = self.d(ref=self.MAIN, apk="release", exe="unsigned", verified=True)
        self.assertTrue(mac.internal_upload)
        self.assertFalse(win.internal_upload)


if __name__ == "__main__":
    unittest.main()
