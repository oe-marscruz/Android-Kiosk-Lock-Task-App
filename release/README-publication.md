# Publication gate (P1b)

This is how CI decides whether a build is published. It implements ARCHITECTURE.md §7.2 and is **default-deny**: anything not listed below is denied.

## What publishes today

**Nothing.**
- Windows signing isn't configured, and RFC 3161 validation isn't implemented yet (see [TODO](#todo)). So no `.exe` qualifies for the only public release path.
- No verified private destination exists, so internal uploads are suppressed. The log says: `internal upload suppressed: no verified private destination`.
- PR runs upload debug test artifacts as described below; artifacts in a public repo aren't private.

The legacy `latest` release and its asset are left untouched. No workflow creates, edits or deletes the `latest` tag. The README's `/releases/latest/download/...` link still serves that legacy build. Retiring it is a separate, user-authorized step.

## How it works

Each platform runs as a single job: build, sign (Windows), verify, classify, then publish. The final bytes never leave the job. The two platforms are evaluated independently.

- `scripts/classify_candidate.py` verifies the candidate and classifies it on three axes:
  - **Capability: `usb-only` or `remote-capable`.**
    - `REMOTE_FEATURES` (set in the workflow's `env`) must be exactly `0` or `1`.
    - Any path in `release/remote-inventory.txt` makes the build remote-capable. The script checks for it in the checkout, in the package contents (the PyInstaller TOC, PYZ module names and DMG files), and as a dex class prefix inside every packaged APK.
    - A mismatch with the flag, an unknown inventory line or an unknown checkout or package layout fails the build.
  - **APK: `release`, `debug` or `release-unpinned`.**
    - The script runs `apksigner verify --print-certs` and a SHA-256 independently, and both must match `build/apk-info.txt`. There must be exactly one signer.
    - A debug APK is never relabelled. A "release" signed with the Android debug key fails.
    - A release APK must match `vars.KIOSK_CERT_SHA256`. If that variable is unset, the APK is `release-unpinned` and is never eligible.
  - **EXE: `authenticode-signed` or `unsigned`.** This comes from `build/authenticode-evidence.txt`, which must be bound to the final EXE's digest. A signed EXE that is missing any proof counts as `unsigned`.
- **Embedded APKs.**
  - **EXE.** `package-win.sh` and CI bundle the APK as a plain PyInstaller data file (`--add-data ...apk;.`). The script reads the final EXE with the pinned PyInstaller's `CArchiveReader`, which only parses the archive and executes nothing. It requires exactly one entry, named `CU-Denver-Equity-Kiosk.apk`, with the verified hash and signer.
  - **DMG.** CI mounts the final DMG read-only (`hdiutil attach -readonly`, and detaches it on every exit path). Every `.apk` on the volume and inside the app's PyInstaller executable must be the verified APK. The macOS app doesn't embed the APK today; the only copy is `Kiosk-APK/`.
- **Mutation steps.** Each one checks its step-output allow flag, `github.event_name == 'push'` and the exact ref. The public release step also rechecks the final digest immediately before it publishes.
- **Permissions.**
  - The default is `contents: read`.
  - `build-exe.yml` calls `windows-candidate.yml` for PR, non-tag and tag runs. Only the job that runs on a `v*` tag push gets `contents: write`.
  - Only the tag-push release job uses the `release-signing` environment and references signing secrets. Dispatch, branch pushes and PRs build debug APKs and unsigned EXEs.

## Matrix (as implemented)

| Platform | Event and ref | Class | Result |
|---|---|---|---|
| Windows | `push`, `refs/tags/v*` | usb-only / release / authenticode-signed | Labelled versioned release (`make_latest: false`) |
| Windows | `push`, default branch | usb-only / debug / unsigned | Internal upload, only with a verified private destination (none exists yet) |
| macOS | `push`, default branch or `v*` tag | usb-only / debug or release | Internal upload, only with a verified private destination (none exists yet) |
| Any | `pull_request`, `workflow_dispatch`, any other event or ref | any | Deny |
| Any | any | remote-capable, `release-unpinned`, or anything else | Deny |

These rows are narrower than §7.2:
- The default-branch Windows **public prerelease** isn't wired up.
- **Remote-capable** builds are always denied. Their evidence gates (P0, P5b, §5.7, fleet upgrade, §7.3) don't exist yet.

The versioned release sets `make_latest: false`, so the README's `/releases/latest` selector keeps pointing at the legacy build.

## Signing environment setup (operator action)

Create the protected GitHub environment `release-signing`, restrict its deployment branches and tags to `v*` tags, and configure required reviewers. Add the Android keystore and Windows signing secrets listed below as environment secrets, then delete their repository-level copies. GitHub environment protection is configured outside these workflows; the workflows cannot enforce these settings. Verify the restrictions and reviewers before enabling signing.

## Repository variables and secrets

| Name | Kind | Purpose |
|---|---|---|
| `KIOSK_KEYSTORE_B64`, `KIOSK_KEYSTORE_PASS`, `KIOSK_KEYSTORE_ALIAS` | environment secret | Release-sign the APK (§7.1). Without them the APK is debug. |
| `KIOSK_CERT_SHA256` | variable | Approved release signer fingerprint. Required for a release APK to count as `release`. |
| `WINDOWS_SIGNING_CERTIFICATE` | environment secret | Base64 PFX. If present, the EXE is signed with `/fd SHA256 /tr <url> /td SHA256`. |
| `WINDOWS_SIGNING_PASSWORD` | environment secret | PFX password. |
| `WINDOWS_TIMESTAMP_URL` | variable | RFC 3161 timestamp server. Required when signing. |
| `WINDOWS_SIGNER_THUMBPRINT` | variable | Pinned signer thumbprint. Required when signing; a mismatch fails. |
| `PRIVATE_ARTIFACT_DESTINATION` | variable | Restricted internal upload target. **Not used yet:** no verifier exists, so it's treated as unverified and nothing uploads. |

When signing is configured, CI also runs `signtool verify /v /pa /all /tw`. It fails on a non-zero exit, on any `Warning` text, or on a signer that doesn't match the pin. More than one signature makes the EXE ineligible. Signing never falls back to unsigned.

## TODO

- **RFC 3161 per-signature validation.** A pinned PKCS#7 parser (pinned by version and digest) must check every signature's RFC 3161 token (OID `1.3.6.1.4.1.311.3.3.1`): the token signature, the TSA chain, the time, and the message imprint against that signature. Until that's done, the signing step writes `rfc3161_validated=false`, so even a validly signed EXE is classified `unsigned` and never publishes (fail closed).
- **Private destination verifier and upload step** for internal builds. Each upload must carry the debug warning that the classifier already prints.
- **Duplicate CArchive entries.** `CArchiveReader` keeps one entry per name, so a duplicate `.apk` name can't be detected.

## PR test artifacts (user decision 2026-11-20)

A `pull_request` into the default branch builds a **debug** candidate and uploads it as a GitHub Actions artifact on that PR run, kept for 14 days:
- Windows: `pr-<n>-windows-usb-or-remote-debug-unsigned`
- macOS: `pr-<n>-macos-debug`

Each artifact contains the package, `apk-info.txt`, `candidate-record.txt` and `DEBUG-BUILD-WARNING.txt`.
- **Not a fleet release.** Never install one on a fleet tablet.
- **Public.** The repository is public, so anyone with read access can download these artifacts. This has been accepted.
- **No secrets.** PR jobs get no secrets and a read-only token. The APK is debug-signed, and the EXE is unsigned.
- **No release changes.** PR jobs never create, edit or delete a release.
- **Classifier gate.** The classifier allows the PR artifact only when all of these hold:
  - the APK is `debug`
  - on Windows, the EXE is `unsigned`
  - `GITHUB_BASE_REF` is the default branch
- **Legacy download kept.** The `latest` release, its asset and the README `/releases/latest` link are kept, not retired (user decision). Normal builds never touch them.

