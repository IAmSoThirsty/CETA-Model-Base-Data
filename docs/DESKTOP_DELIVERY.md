# CETA desktop delivery

## Product scope

CETA is the official name of the native, installable desktop environment for coding, everyday
conversations, and user-directed workloads. Windows x64 is the first delivery
target. Application updates are downloadable; AI models are optional expansion
packs supporting local inference. CETA disables cloud features when launching
Ollama; separately managed services retain their own privacy settings. No model
weights are bundled or downloaded implicitly.

The existing CETA reference and training package remains independently testable.
Its historical model evaluations are not evidence for desktop application quality.

## Release acceptance

- Native workspace browser and editor, with explicit saves and conflict detection.
- Persistent conversations, model selection, cancellable inference, and useful
  offline/no-model behavior.
- User-started workloads with visible output and cancellation; model text alone
  cannot execute commands or change files.
- Local model installation and validation, with no execution of model-pack code.
- Update verification and a recoverable installation path preserving user data.
- Windows installer, uninstall support, version metadata, and dependency notices.
- Automated backend and GUI checks, clean-machine installation smoke tests,
  restart/data-preservation checks, and an evidence-backed release report.

## Current release classification

The application has been renamed to CETA by the user's instruction on September 6,
2026. The window, launcher, Windows installer identity, and update signature domain
now use CETA. The latest verified local candidate is not a published production
release. Public release-channel delivery remains unverified at this checkpoint.
The user subsequently authorized a dedicated page
and direct download on `thirstysystems.com` through the "Thirstys Projects LLC"
website project, release hosting in the existing CETA GitHub repository, and all
required signing. This permits the delivery work and does not itself prove that
publication or signing succeeded. See
`docs/operations/CONTINUITY_MAP.md` for checks performed after the rename.

The user then expressly declined a Microsoft signing subscription and selected a
personal signing artifact for recipients to verify installation identity. A
dedicated CETA Ed25519 key has been generated and protected with current-user
Windows DPAPI outside the repositories. The verification bundle binds the exact
installer to that key and requires an independently received key fingerprint.
This is personal publisher verification, not Windows CA signing; Windows may
display an unrecognized-publisher warning. No other project's certificate is used
and no root certificate is installed. Release build 003 embeds the HTTPS channel
and public key. Its signed update manifest and public verification bundle have
been created and verified locally; public hosting and website publication remain
pending at this checkpoint.

### Current desktop 0.3.1: redesigned release build 004

CETA desktop 0.3.1 now has the seven native sections Chat, Projects, Library,
Models, Workloads, Updates, and Settings, with distinct planetary backgrounds,
native message/code presentation, conversation search and export, and saved
editor preferences. Desktop version 0.3.1 and the reference package's `VERSION`
0.3.0 are intentionally independent; this release does not rename or retrain the
reference core. The approved visual direction is in `docs/CETA_VISUAL_DESIGN.md`.

The actual installer is `CETA-0.3.1-setup.exe`, 43,492,467 bytes, SHA-256
`6debcf31c8822bb27791e839194bd272f8fcffcd4abebd427b2ab89f7147c0e2`.
Its six-file personal distribution payload is retained at
`dist/CETA-0.3.1-personal-001` in the original checkout. The new record
`evidence/CETA_EMBER_RELEASE_VALIDATION.json` binds those actual files, the
21-file source synchronization, and the current build/test/Sandbox records.

The build ran 118 desktop tests: 117 passed and one Windows short-alias test
explicitly skipped because this host provides no distinct alias. The full
delivery repository run executed 293 tests in 239.197 seconds: 292 passed and the
same one skipped. No known vulnerabilities were reported for the isolated desktop
build dependencies. These totals include the skip; they are not 118 or 293 passes.

A fresh network-disabled Windows Sandbox passed all nine installer lifecycle
checks, including startup of the redesigned application, same-version replacement,
uninstall, and preservation of application data and unknown files. Parent-process
timeout returned 4 and successful wait returned 0. This does not verify upgrading
from an older database schema or updating through a live public channel.

The standalone verifier passed against the actual 0.3.1 installer and personal
Ed25519 receipt. Windows Authenticode remains `NotSigned`; no Windows CA trust
is claimed. Public 0.3.1 release assets, website delivery, live update checks, and
new Windows CI remain pending at this checkpoint. Refresh package manifests after
this evidence/documentation addition before publishing the reviewed source.
The separate training dependency gate for Transformers 5.5.0 / CVE-2026-9856
remains unresolved and is excluded from this desktop dependency result.

### Historical personal release build 003

The installer at this earlier checkpoint was `CETA-0.3.0-setup.exe`, 29,988,504 bytes,
SHA-256 `416bf6d702342ec9a38be733f207319f77d377c9823aa4c694e2f02917c08bfc`.
It was built in the external CETA build directory `release-003`, from the same
repository's `codex/ceta-desktop-release` delivery worktree. Its source assembly,
artifact paths, public verification files, and validation logs are bound in
`evidence/CETA_PERSONAL_RELEASE_VALIDATION.json`.

The standalone public verifier passed against the exact installer, signed
`CETA-UPDATE.json`, and independently pinned public-key SHA-256 fingerprint:

`583b329e113816d2bcbcaf63fe796d4d3e8d0b9e9afe15fa0caf41954c9273bb`

The installer remains `NotSigned` under Windows Authenticode. The valid personal
Ed25519 receipt proves correspondence to this publisher key, not CA-validated
legal identity or Windows trust. Recipients must receive the fingerprint through
an independently trusted contact with the publisher. The public verifier requires
Python 3.11 or later and its declared cryptography dependency; it never runs the
installer or makes network requests.

The build passed 93 desktop tests in 13.671 seconds and its isolated dependency
audit reported no known vulnerabilities. The delivery checkout separately passed
93 desktop tests, six release-safety tests, and all 268 repository tests in
190.150 seconds. Import provenance confirms that the full suite used delivery
source, including the public base reference core. Five original dirty core/verifier
files were preserved in the original checkout and excluded from the release
assembly; these test results do not validate those separate local edits.

A fresh network-disabled Windows Sandbox passed installation, dependency notices,
startup, replacement update, uninstall, database-file and unknown-file preservation.
It rejected a still-running test parent with exit code 4 and installed after that
parent exited with code 0. These controlled process tests do not establish a real
installed application updating through the published channel or migration to a
future database schema. No new training epoch or model-quality evaluation is claimed.

Release build 003 includes the configured channel and redirect restrictions for
GitHub release downloads. Public release assets, the website page, public channel
responses, and an end-to-end installed-application public update remain unverified.
Package manifests must be regenerated after these delivery notes and new evidence
are included; the preceding 251-file package check predates this finalization.

### Historical candidate 002

Candidate 002 remains in `dist/CETA-0.3.0-candidate-002`. It includes explicit
installation handoff after a verified download. All 56 desktop tests passed during
the build; the isolated desktop dependency audit reported no known vulnerabilities.
A network-disabled Windows Sandbox passed installation, startup, replacement
update, uninstall, and preservation checks for the database file and unknown files.
It also verified installer rejection of a still-running parent (exit code 4) and
successful installation after that parent exits (exit code 0). Those process-wait
tests used a controlled PowerShell parent. An interactive update through a real
public channel is still unverified.

The full repository test log reports 230 tests passed. The separate reference
validation completed all 16 commands, including architecture/corpus/curriculum,
hostile gates, retained training-report checks, and the reference runtime demo.
These are local verification results, not a new training epoch or a certification
of model quality. `evidence/CETA_DESKTOP_UPDATE_HANDOFF_VALIDATION.json` binds the
candidate artifacts and retained results, and distinguishes the current source
snapshot from a build-time input attestation.

Candidate 001 and `evidence/CETA_DESKTOP_RENAME_VALIDATION.json` remain preserved
as the earlier rename checkpoint. Its 47-test result has not been relabeled as
validation of candidate 002.

The last installer built before the rename is in `dist/ThirstyAI-0.3.0-candidate-009`, with its
dependency-source companion. `evidence/THIRSTYAI_DESKTOP_PRIVACY_VALIDATION.json`
records this artifact and its source hashes. The earlier desktop validation
reports remain historical records of their respective artifacts. Their names,
hashes, and test results have not been relabeled as CETA validation. The source
hashes in those reports describe the earlier source, not the renamed application.

## Historical validation before the application rename

- Full repository verification: 215 tests passed, with architecture, corpus,
  curriculum, hostile audit/gate, report verification, and reference demo passing.
- Desktop-focused validation: 41 tests cover persistence, editor conflicts,
  draft recovery, workload execution/cancellation, local model transport, model
  pack integrity, signed update metadata, and narrow network-import boundaries.
  The total includes three dependency-notice tests checking archive identity,
  attribution references, and path-escape rejection, plus four publisher-signing
  workflow tests and a process-environment test for disabling Ollama cloud features
  without modifying inherited parent settings. That pre-rename build ran all 41.
- Isolated desktop dependency audit: no known vulnerabilities reported.
- Real `qwen3:0.6b` installation through Ollama 0.33.3, followed by a native UI
  conversation over loopback and verified conversation persistence after restart.
  This is an integration smoke test, not a model quality benchmark.
- Native source UI in a network-disabled Windows Sandbox started its own Ollama
  service using the already installed model. Runtime logs confirmed cloud features
  disabled; the saved answer exactly matched the observed model stream, survived
  restart, and closing the application stopped its service. The separately tested
  frozen installer is identified by checksum in the validation report.
- Windows installer creation; installed executable startup; update over the test
  installation preserving conversation data and an unrecognized file.
- Installer rejection while the application's Windows marker is active.
- Uninstall of the first test installation preserved an unrecognized file.
- Wheel build and desktop startup from an isolated wheel installation.
- Clean Windows Sandbox lifecycle validation: install, startup, update, uninstall,
  application-data preservation, and unrecognized-file preservation all passed.
  This is replacement of the test installation; it does not establish migration
  compatibility with a future database schema.

## Problems and classification

- Fixed: stale package manifests; recursive release cleanup; non-manifest payload
  inclusion; unsafe manifest paths; output collisions.
- Fixed: the first frozen build captured an unrelated ICU DLL through host PATH.
  Building with isolated library search paths produced a working executable.
- Fixed: the original blanket network-import rule conflicted with the requested
  desktop transports. Only the exact local-model and signed-update transport
  modules now receive import allowances; core imports remain restricted.
- Fixed: model cancellation could leave a blocked Windows socket read waiting;
  worker-owned reads now check cancellation while allowing model-loading time.
- Fixed: editor draft loss after cancelled file dialogs; missing conversation
  drafts and interrupted-response checkpoints; oversized requests consuming drafts.
- Fixed: untested update download publication and cancellation paths; malformed
  model manifests hiding valid packs; CR-only file conversion and oversized saves.
- Fixed in candidate 002: a downloaded update previously required the user to
  locate and launch it manually. CETA now confirms installation, handles active
  work and unsaved-file cancellation, rechecks the installer under a Windows file
  lock, and launches it after releasing application resources. The installer waits
  for the exiting application before replacing files and fails on a bounded timeout.
- Fixed: the binary Qt Python wheels supplied only commercial-reference license
  files. The build now collects the open-source license texts and attribution
  references from checksum-verified matching source archives and produces a source
  companion. Both installer and source companion must be published together.
- Fixed: an upstream license filename exceeded the Windows path-length limit in
  the build folder. Installed notices now use short names with an index retaining
  their source paths and unchanged text.
- Fixed: publisher signing previously required an unspecified manual process.
  The builder now supports an explicit signing configuration and verifies the
  application, generated uninstaller, and installer when that option is supplied.
  Real trusted signing still requires successful execution using a trusted
  publisher identity and verification of the final artifacts.
- Fixed: application-started Ollama inherited its cloud setting, while the status
  bar implied that all conversation processing stayed on the computer. ThirstyAI
  now sets `OLLAMA_NO_CLOUD=1` for its own Ollama process, describes local storage
  accurately, and explains that separately started services may forward prompts.
- Environment/dependency issue, isolated from desktop: the retained language
  training environment has Transformers 5.5.0, reported by pip-audit as affected
  by CVE-2026-9856, with 5.10.0 reported as fixed. Training dependencies are excluded
  from the desktop build. Updating that pinned training contract and revalidating
  its model workflow requires separate follow-up work; historical evidence has
  not been rewritten or represented as a new-stack validation.
- Resolved after the rename: Codacy MCP is installed and local analysis has run.
  Its current findings and tool-environment limits are recorded in
  `docs/operations/CONTINUITY_MAP.md`.
- Validation finding, not blocking desktop transport: in the network-disabled
  Sandbox, the optional `qwen3:0.6b` model answered `Local OK.` when asked for
  `LOCAL_OK`, failing the exact-text assertion. That failed result is retained.
  Model instruction accuracy is separate from delivering and retaining the actual
  response; this candidate makes no model-quality claim.
- Environment issue, not blocking delivery: the attempted user Documents output
  directory was unavailable. The reviewable release files are instead placed in
  the repository's ignored `dist/ThirstyAI-0.3.0-candidate-009` directory.
- Current delivery decision: personally signed verification is complete locally;
  Windows CA-backed signing is not selected. Public hosting, the dedicated website
  page, live channel responses, and an installed application completing a real
  public update remain authorized but not yet verified here.

## Reproduce the Windows build

Use a separate environment so training dependencies cannot enter the desktop
payload. Set `UV_PROJECT_ENVIRONMENT` to a new external directory, then run:

```powershell
uv sync --locked --no-install-project --extra desktop --group desktop-build --group ci --no-default-groups
uv run --no-sync python scripts/build_desktop.py --output <new-external-output-directory> --makensis <NSIS-3.12-Bin-makensis.exe> --dependency-sources <Qt-source-archive-directory>
```

The builder audits dependencies, runs desktop tests, freezes the native executable,
includes dependency notices, and creates an NSIS installer, dependency-source
companion, and SHA256SUMS. Download the three source archives listed in
`licenses/desktop-sources.json` into the supplied source directory first. The
builder verifies each archive against the recorded upstream SHA-256 checksum. It
refuses existing output directories and environments containing training packages.
The default build is unsigned. Supplying `--signing-config` enables signing and
verification of the application executable, the generated uninstaller, and the
final installer. Any signing, trust-verification, or timestamp-verification failure
stops that build. The output checksums are calculated after signing.

Supply `--channel-config` with an HTTPS manifest URL and a base64 Ed25519 public key
to embed a publisher channel. Keep the corresponding private key outside the
repository. `scripts/sign_desktop_update.py` signs manifest metadata for an already
prepared installer. Windows Authenticode signing and update-manifest signing are
separate release steps. Release build 003 uses a verified Ed25519 manifest and
personal verification bundle; Authenticode remains `NotSigned`.

The selected personal workflow uses `scripts/desktop_update_keys.py --output
<new-external-key-file>` to generate a dedicated current-user DPAPI-protected key;
it refuses existing files and repository-local destinations. Keep this private
artifact outside all repositories. `scripts/sign_desktop_update.py
--protected-private-key <key-file>` decrypts it only in memory to sign metadata;
the existing `--private-key` PEM interface remains supported. The public bundle
is created by `scripts/create_desktop_verification.py` without private-key access.

### Publisher signing configuration

Create this configuration outside the repository using the publisher's actual
values, then pass its path as `--signing-config`. The certificate must already
be available in the current Windows user's Personal certificate store, including
access to its associated signing provider. This workflow does not create a
certificate or export its private key.

```json
{
  "signtool": "C:\\Program Files (x86)\\Windows Kits\\10\\bin\\<SDK-version>\\x64\\signtool.exe",
  "certificate_thumbprint": "<40 hexadecimal characters from the publisher certificate>",
  "timestamp_url": "https://<publisher-approved-RFC3161-service>"
}
```

The builder takes a snapshot of these non-secret settings so the application,
uninstaller, and installer use the same configuration. It invokes Windows SDK
SignTool with SHA-256 file and timestamp digests and verifies trust and timestamps
after signing. The NSIS uninstaller callback is checked by the compiler.

Four deterministic tests cover selected-certificate arguments, required fields,
signature-verification failures, and uninstaller callback construction. A real
NSIS compilation using a deliberately failing test signer also aborted at the
uninstaller callback. These checks prove the failure path, not possession of a
publisher certificate or successful trusted signing.

Primary command references: [Microsoft SignTool](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool)
and [NSIS compile-time commands](https://nsis.sourceforge.io/Docs/Chapter5.html).

`scripts/verify_desktop_inference.py --endpoint <loopback-v1-url> --model <installed-model-name> --output <new-external-directory>`
repeats the native real-model conversation and restart check. This helper does
not install or download models.

## Requirement-by-requirement completion check

| User requirement | Implemented and verified | Release limit or remaining input |
| --- | --- | --- |
| Native downloadable desktop application | Standalone Windows x64 executable, per-user installer, clean Windows startup, verified personal receipt | Authenticode NotSigned; public delivery pending; Windows x64 only |
| Coding and everyday workloads | Workspace editor, explicit file context, native command execution, workload history and Stop | UTF-8 text files up to 4 MiB; one open editor document; noninteractive commands |
| Daily conversations | Local streaming chat, conversation history and exports, independent drafts, restart recovery | A separately installed model runtime and model are required for chat |
| Installable AI expansion packs | Ollama download flow and GGUF import, checksums, integrity checks before GGUF launch | Model quality and hardware needs depend on the selected model; no weights bundled |
| Downloadable application updates | Configured channel and public key, signed manifest, bounded download, checksum/size checks, cancellation, explicit installation handoff, and installer wait/data-preservation tests | Publish and verify the public channel; complete a real installed-application update through it |
| Distribution and maintenance | Dependency audit, library notices and source companion, personal verification bundle, automated desktop checks, reproducible build and validation helpers | Publish the installer, source companion, and verification bundle together; verify release hosting |

The desktop does not currently expose the retained CETA reference runtime's
governed execution APIs. Desktop commands are explicit user actions. Historical
CETA training evidence is not a desktop autonomy or model-quality certification.

## Baseline inspection

Checkout: `codex/ceta-curriculum-v3` at `decd957ef91884e5ba9fc61c627fb5481d53a80f`,
with six existing modified files and an untracked editor instruction file preserved.
The existing full verification passed 169 tests, structural validators, hostile
checks, report verification, and the reference effect demo on local Python 3.12.10
and CPU PyTorch 2.13.0. This did not execute H100 training.

Package manifests were stale at baseline. Release creation previously deleted
caches and admitted non-manifest files; those safeguards have been repaired.
Codacy MCP was unavailable at that original baseline. It is now installed and
native tools are available; current findings and environment limits are recorded
in `docs/operations/CONTINUITY_MAP.md`.
