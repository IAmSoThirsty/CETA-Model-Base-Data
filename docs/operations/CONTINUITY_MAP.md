# CETA desktop delivery continuity

Date: September 6, 2026. Scope: the existing CETA repository and the expressly
authorized delivery work described below. Preserve the reference/training core,
earlier local changes, historical evidence, and project boundaries.

## GitHub publication validation: September 6, 2026

The reviewed desktop source and a merge retaining the remote V3.1 verification
block were pushed to the existing repository's main and desktop delivery branch
at `435585d90b7a22ea0170e8d91a7ef1f3ee1b764e`. The five protected original
core edits remain unchanged and are excluded from this delivery. All 252 manifest
payload entries and 253 checksum entries matched the prospective Git blobs.
Three historical JSON evidence files retain their original CRLF or mixed bytes
through explicit Git attributes; they were not reformatted.

The first Windows CI run executed 93 desktop tests and found one test assertion
that compared a short Windows directory alias with the runtime's canonical path.
The runtime correctly resolved and locked the installer. The expected path now
uses strict resolution, and another test exercises a real Windows short alias
while retaining the write/delete-denial and process-launch assertions. The local
targeted run executed six tests: five passed, and alias coverage explicitly
skipped because this host's temporary volume exposes no distinct short alias.
No application runtime or installer bytes changed for this test correction.

The separate reference workflow remains blocked by `transformers==5.5.0`,
`CVE-2026-9856`, whose reported fix is 5.10.0. This is a training dependency,
excluded from the isolated desktop payload; its repair requires separate
training compatibility validation. The desktop dependency audit passed. Neither
the reference failure nor the first Windows assertion failure is represented as
a passing GitHub check. A subsequent Windows CI result and actual public delivery
will be recorded separately.

## Current authorization and delivery work

The user expressly authorized a dedicated CETA showcase page and direct download
link on `thirstysystems.com`, using the website project identified as
"Thirstys Projects LLC", the existing CETA GitHub repository, and the signatures
required for delivery. This authorizes carrying CETA product descriptions and
verified release links to that website, publishing CETA release assets through
`IAmSoThirsty/CETA-Model-Base-Data`, and configuring the CETA update channel and
publisher signing. It does not authorize importing that website's code, data, or
other products into the CETA application, or creating another CETA repository.
The website checkout and delivery path must be verified in that project before
editing or publishing there. Authorization is not evidence of publication or a
trusted signature; those actions require their own verified results.

## Personal signing decision and current release work

The user explicitly declined Microsoft's monthly signing subscription and asked
for a personalized signing artifact recipients can receive directly from the
publisher to verify installation identity. This supersedes CA-backed signing as
the current delivery method. CETA now has a dedicated Ed25519 key protected by
Windows DPAPI for the current user, stored outside all repositories in the user's
private signing directory. No other project's certificate or key was used, no
subscription was created, and no system trust store was changed.

The personal verification bundle now binds the exact installer bytes to that key
and has passed the standalone public verifier locally.
Recipients must obtain the public-key fingerprint independently from the
publisher. It does not establish CA-validated legal identity or Windows publisher
trust. The public channel configured in source is
`https://www.thirstysystems.com/ceta/updates/stable.json`; publication and public
download verification are still pending at this checkpoint.

Delivery worktrees were created in the existing projects so reviewed release work
can be published without committing unrelated local changes. CETA's delivery
branch is `codex/ceta-desktop-release`, based on the current CETA HEAD `decd957`.
The five pre-existing CETA runtime/verifier edits and editor instruction file
remain in their original workspace; they are not treated as desktop changes.
The website delivery branch is `codex/ceta-showcase`, based on its current remote
main `7107dbc`. The original website main and its unpublished disclosure commit
remain preserved. The user separately authorized a read-only background audit
of website delivery gaps; that audit does not authorize publishing its findings
or applying the unrelated site changes.

## Personal release build 003: verified local checkpoint

The new evidence record is `evidence/CETA_PERSONAL_RELEASE_VALIDATION.json`.
Its retained external source is
`C:\Users\Quencher\.codex\audits\CETA-personal-release-20260906`.
Build and test commands used `T:\00-Active\CETA-desktop-delivery-20260906` at base
HEAD `decd957ef91884e5ba9fc61c627fb5481d53a80f`, with the reviewed desktop overlay.
The assembly record binds 53 copied files. A subsequent addendum records the
focused package-verifier fix that excludes a worktree's `.git` marker as Git
metadata. That marker and the original five dirty core/verifier files remain
unchanged. Their contents were not included as desktop release changes.

- Installer: `CETA-0.3.0-setup.exe`, 29,988,504 bytes, SHA-256
  `416bf6d702342ec9a38be733f207319f77d377c9823aa4c694e2f02917c08bfc`.
- Dependency-source companion SHA-256:
  `063ed318ffdc8bf7e843cc47094ac721aab70218f36623f25406326bb0024778`.
- Standalone public verification: PASS against the signed update envelope and
  public-key fingerprint
  `583b329e113816d2bcbcaf63fe796d4d3e8d0b9e9afe15fa0caf41954c9273bb`.
  This reconciliation read only public verification material, not private keys.
- Windows Authenticode: `NotSigned`. The user selected personal verification;
  no Windows CA trust or removal of SmartScreen notices is claimed.
- Build: exit 0, isolated desktop audit reported no known vulnerabilities,
  93 desktop tests passed in 13.671 seconds. The frozen channel matches delivery.
- Delivery validation: 93 desktop tests in 15.817 seconds, six release-safety
  tests in 0.044 seconds, and 268 full repository tests in 190.150 seconds passed.
  Module paths were verified to resolve to delivery source and its public base
  core. These results do not validate the five excluded original local core edits.
- A fresh network-disabled Windows Sandbox passed install, notices, startup,
  replacement update, uninstall, database-file preservation and unknown-file
  preservation. Controlled parent-process timeout returned 4; successful wait
  returned 0. This does not prove interactive updating through a public channel.
- Ruff F/E9 and delivery diff checks passed before these documentation additions.
  No new GPU training epoch or model-quality claim follows from these tests.

The assembly timestamps and hashes are retained as provenance, not rewritten as a
signed build-input attestation. The evidence records the current relevant source
snapshot and its comparisons with the assembly/final-validation records; these
notes and the new evidence were finalized after the installer build. Historical
candidate records retain their own names, bytes, hashes, and validation scope.

The preceding package verification passed with 251 registered payload files.
The release coordinator must regenerate manifests/checksums after this final
documentation and evidence addition, then verify the complete package before
publication. Public GitHub release assets, website publication, live update
manifest delivery, and a real installed-application public update remain pending.

## Historical update installation handoff and candidate 002

The application now offers **Install update and close CETA** after a verified
download. It checks for active work, asks for the user's installation decision,
honors unsaved-editor cancellation, closes its database and running marker, and
launches the verified installer without a command shell. Immediately before
launch, it rechecks the installer size and checksum under a Windows file lock
that denies writes and deletion. The installer receives the exiting process ID,
waits for that process to finish, and rejects an unfinished process with exit
code 4 after its bounded wait. A launch failure reports how to reopen CETA.

The candidate at this earlier checkpoint was
`dist/CETA-0.3.0-candidate-002/CETA-0.3.0-setup.exe`.

- Installer SHA-256:
  `00065daf52322a9ea469a4b8f563b49193d5d2c0185f1d112878a7463fd7874a`.
- Dependency-source companion SHA-256:
  `063ed318ffdc8bf7e843cc47094ac721aab70218f36623f25406326bb0024778`.
- Windows Authenticode status checked during reconciliation: `NotSigned`.
- This candidate's build reported `built_unsigned_not_published`. Its then-current
  source channel configuration had no publisher URL or public key.

The completed results are preserved in
`C:\Users\Quencher\.codex\audits\CETA-update-handoff-20260906T193309Z`.
`evidence/CETA_DESKTOP_UPDATE_HANDOFF_VALIDATION.json` records their checksums,
the candidate hashes, and a current source snapshot. The snapshot is recorded
after the build and is not a build-time attestation of its exact input bytes.

- The build's isolated desktop dependency audit reported no known vulnerabilities.
- All 56 desktop tests passed in 8.108 seconds during that build.
- The repository test log reports 230 tests passed in 117.730 seconds. The printed
  H100 device line comes from the test run; it is not evidence of a new GPU epoch.
- The completed reference validation records 16 commands with exit code 0:
  corpus, architecture and source/evidence validators, both curricula, hostile
  checks, bounded models, retained training-report checks, and the runtime demo.
  It also parsed 134 Python files. No new training epoch was run.
- A fresh, network-disabled Windows Sandbox passed install, dependency notices,
  startup, replacement update, uninstall, database-file preservation, and
  unrecognized-file preservation. The timeout test returned 4 without changing
  the installed executable; the completed-parent test returned 0 after exit.
  The wait tests used a controlled PowerShell process as the exiting parent.
- The GUI and backend tests cover confirmation/cancellation and protected launch;
  the Sandbox covers installer lifecycle and process waiting. This combination
  does not yet establish an interactive click-through of a real public update
  from the installed application, or migration to a future database schema.
- Native Codacy tools are now available in this task. The seven-file handoff
  analysis completed with 291 findings (214 notes and 77 warnings), including
  existing style and static-review findings. This is not a clean-analysis claim.

## Current limits and next evidence

Personal signing and local channel configuration are now verified for build 003.
Public release delivery, website publication, and the installed application's
public update flow remain unverified at this checkpoint.
The latest user authorization permits that delivery work; the outstanding items
are implementation/verification requirements rather than missing publishing
permission. The remaining Codacy findings and isolated tool/training dependency
issues below still require their separately scoped review.

The earlier package verification below belongs to candidate 001. Package manifests
must be refreshed and checked after the new source and evidence are included;
that older result does not verify the current working-tree payload.

## Historical rename and isolation work

### Earlier user authority

The user designated CETA as the official application name, authorized removal of
the unrelated project reference, and requested rules prohibiting project mixing
without express authority. The user subsequently authorized making Codacy
available. These instructions authorize this correction and shared tool setup;
they did not authorize importing another application's source or publishing CETA.
The later explicit publishing authorization is recorded above.

### Rename changes

- Application UI, launch entry point, installer paths and metadata, shortcuts,
  registry keys, Windows mutex, update product and signing domain now use CETA.
- The user guide is `docs/CETA_USER_GUIDE.md`; public documentation and dependency
  notices use the official name.
- New data uses the CETA folder. An existing pre-release database remains usable
  in place when there is no CETA folder. Folders are never implicitly moved or
  merged, and an explicit `--data-dir` remains supported.
- Removed the unrelated archive path from the delivery document. Historical
  installers and validation reports retain their authentic names and hashes.
- Created `T:\PROJECT_ISOLATION_RULEBOOK.md`; linked its rules from global Codex
  `AGENTS.md`, `T:\AGENTS.md`, and this repository's `AGENTS.md`. These are agent
  operating instructions, not a machine-enforced sandbox.

### Verification performed for candidate 001

- 47 desktop tests passed, including six new tests for data-folder compatibility,
  installer identity/mutex coordination, and update signer/verifier compatibility.
- Ruff checks for F and E9 passed on the application and changed Python files.
- Five release-preservation tests passed.
- The isolated desktop build reported no known dependency vulnerabilities and
  passed all 47 tests again before producing the installer.
- Packaged `CETA.exe --smoke-test` exited 0, created its separate test database,
  and produced a screenshot inspected for the CETA application name.
- Installer Windows metadata reports product CETA, description CETA desktop
  installer, version 0.3.0. No publisher signature or publication is claimed.
- A streaming scan of 28,730 working files (including ignored files and binary
  strings in ASCII and UTF-16) found zero references to the unrelated project,
  with no read failures. Git internals and decompressed archive members were
  outside that scan.

### Candidate 001 artifacts

`dist/CETA-0.3.0-candidate-001/CETA-0.3.0-setup.exe`

SHA-256: `33cb87af6636e6d795b671c74622e3fd8e8a44259d72de85f8aa884b8d905467`.

`dist/CETA-0.3.0-candidate-001/CETA-0.3.0-dependency-sources.zip`

SHA-256: `02e73befd8ca27870b71f5a57e9c46154e7f7997b60b12a5d3e1b4fbafb7a4c0`.

Both files and their checksum file are new artifacts. Earlier build outputs and
the external forensic audit remain preserved.

### Initial Codacy setup and findings

Codacy MCP 0.6.24 is installed in `T:\02-Config\codacy` and registered in the
global Codex configuration. Codex launches it directly with Node. MCP initialization,
tool discovery, and real local analysis succeeded. No Codacy account token is
configured; private cloud-account operations are not connected. The existing task's
native tool list has not refreshed, so these checks called the installed server
through the MCP protocol directly.

The initial changed-file sweep completed 27 MCP analysis calls: 26 individual files
and a Trivy source scan. It returned 521 findings (425 notes and 96 warnings), not
a clean-analysis verdict. Complete results are preserved outside this repository
in `C:\Users\Quencher\.codex\audits\CETA-codacy-20260906T142821Z`.

- Requires separate follow-up: formatting/documentation findings and static
  review warnings in the existing desktop implementation. The rename does not
  certify the complete application free of these findings.
- Not blocking this correction: instruction-file heuristics assume additional
  agent-runtime scaffolding. The explicit user-authority and isolation rules
  remain authoritative; unrelated runtime configuration was not introduced.
- Environment limitation: the Semgrep adapter cannot install its Opengrep binary
  on native Windows. This scanner remains unavailable; no rule was silently
  disabled to claim a full pass.
- Environment/dependency issue: an audit of the Codacy tool installation initially
  found 25 advisories. Compatible overrides for Ajv, Markdown-it, and Minimatch
  reduced that to 14 (9 moderate, 5 high). Remaining advisory chains involve
  decode-uri-component, deepmerge-ts, and fast-xml-parser; resolving them requires
  broader dependency compatibility work or upstream fixes. These dependencies are
  in the separate analysis-tool installation, not in the CETA desktop payload.
- Requires separate follow-up: Trivy reported the retained training-dependency
  advisory in `uv.lock`. Training dependencies are excluded from the desktop build.

Codacy's `.codacy/` configuration is local and ignored. The package manifest,
checksum generator, and verifier exclude that tool state. Trivy skips local
environments, Git internals, analysis caches, and generated build/release directories
for source analysis; source, tests, documentation, manifests, and dependency lockfiles
remain in scope. The isolated desktop dependency audit is recorded separately.

### Limits at the candidate 001 checkpoint

The package manifest and checksums were refreshed. Package verification passed
with 244 registered payload files. The release-preservation tests passed again
after adding the analysis-state exclusion, and focused Ruff checks passed.

At this checkpoint publisher signing and public update-channel configuration
remained release blockers. Full CETA training/reference verification and a new
Windows Sandbox installer lifecycle had not yet been rerun for the rename.
The later candidate 002 results above supersede those missing-validation items
within their stated scope. The retained training dependency issue described in
`docs/DESKTOP_DELIVERY.md` still requires separate follow-up work.


## Desktop 0.3.1 ember redesign: build 004 local checkpoint

The user-directed native redesign has seven sections with distinct planetary
landscapes, native message/code display, conversation search and selected export,
and persistent editor font/wrapping settings. Desktop version 0.3.1 is independent
of the retained reference package VERSION 0.3.0. No new training epoch is claimed.
The 21-file same-repository transfer from delivery back to the original checkout
is recorded in the external `ember-source-sync-001.json`; the protected original
core edits were excluded and remain preserved.

`evidence/CETA_EMBER_RELEASE_VALIDATION.json` binds the current source snapshot,
actual distribution files, and retained logs under
`C:\Users\Quencher\.codex\audits\CETA-personal-release-20260906`.

- Installer: `CETA-0.3.1-setup.exe`, 43,492,467 bytes, SHA-256
  `6debcf31c8822bb27791e839194bd272f8fcffcd4abebd427b2ab89f7147c0e2`.
- Distribution directory: original checkout `dist/CETA-0.3.1-personal-001`,
  containing installer, dependency sources, verification ZIP, publisher public
  metadata, signed update envelope, and checksums. Actual file hashes were checked.
- Build 004: 118 desktop tests ran in 27.668 seconds; 117 passed and one host
  short-alias test skipped. The isolated dependency audit found no known advisories.
- Full delivery suite: 293 tests in 239.197 seconds; 292 passed and the same one
  short-alias test skipped, exit code 0. The printed H100 test diagnostic is not
  evidence that a new hardware training run occurred.
- Fresh Sandbox 004: all nine lifecycle checks passed with networking disabled.
  The installed redesigned Chat screenshot is 1540 by 813 pixels. Installation,
  notices, startup, same-version replacement, uninstall and file preservation were
  checked; timeout code 4 and completed-parent code 0 were retained. The test guest
  was stopped; no other Sandbox was stopped by this validation.
- The actual personal Ed25519 receipt passed the standalone public verifier for
  key fingerprint
  `583b329e113816d2bcbcaf63fe796d4d3e8d0b9e9afe15fa0caf41954c9273bb`.
  Windows Authenticode remains NotSigned. No private key was read during evidence
  reconciliation and no Windows trust-store modification is claimed.

Public 0.3.1 assets, the website download, live channel delivery, a real installed
application's public update, and new Windows CI are still unverified at this
checkpoint. The offline Sandbox is same-version replacement, not proof of an
upgrade from a prior database schema. No model download or inference benchmark
was performed for this checkpoint. Earlier installer records remain unchanged.

The coordinator must regenerate package manifests/checksums after these new docs
and evidence, then verify and publish the reviewed source. The separate reference
workflow gate for Transformers 5.5.0 / CVE-2026-9856 remains unresolved and requires
training compatibility validation; it is outside the isolated desktop payload.

## Native update-client HTTP 403: source fix for desktop 0.3.2

Public 0.3.1 release downloads and the live CETA website were verified, but the
unmodified 0.3.1 updater's default Python request received HTTP 403 at the stable
channel. A separate reader with a CETA user agent returning HTTP 200 did not prove
that the native updater worked. The failed result remains preserved externally;
its diagnostic response body and client network address are not copied here.

The focused fix adds the truthful `CETA/0.3.2` user agent to the updater's normal
manifest and installer requests. Only `src/ceta_desktop/updates.py`, desktop
`__init__.py`, and `tests/test_desktop_updates.py` changed for this correction.
The exact preimages and matching files in both CETA roots are bound by
`evidence/CETA_UPDATE_CLIENT_FIX_VALIDATION.json`. The reference VERSION remains
0.3.0; no model, inference, training, or unrelated project code was changed.

The fixed 0.3.2 source passed 21 updater tests and a focused Ruff F/E9 check.
Its actual request path then received the signed live 0.3.1 manifest and downloaded
the 43,492,467-byte installer with SHA-256
`6debcf31c8822bb27791e839194bd272f8fcffcd4abebd427b2ab89f7147c0e2`.
The test supplied 0.3.0 as the comparison version to exercise update availability;
it did not replace request behavior or execute the downloaded installer.

This validates the patched source against the current public channel. It does
not fix the preserved public 0.3.1 binary or prove a built 0.3.2 update yet.
The new build, its Windows CI, personal receipt, and public release require their
own checks. Personal signing remains separate from Windows Authenticode CA trust.
The existing Transformers 5.5.0 / CVE-2026-9856 training gate remains unresolved
and excluded from the isolated desktop payload. Earlier evidence is unchanged.

## CETA desktop 0.3.2: public delivery checkpoint

The 0.3.2 runtime source is committed at
`340d8b47e872c422d9f6a7602c17f2ad4386869d` in the existing CETA repository.
Read-only source verification matched all 270 committed files, 268 manifest
payloads and 269 checksum entries. The original curriculum branch and its five
dirty core files remain preserved. Build 005 ran 119 tests: 118 passed and one
host-only short-alias case was skipped. Windows CI passed all 119 tests in
43.882 seconds, including that case. CodeQL passed and the isolated desktop dependency audit found no known
vulnerabilities.

All six public 0.3.2 release assets matched their reviewed hashes through
unauthenticated downloads. The personal Ed25519 receipt passed; installer
Authenticode remains NotSigned. Recipients still need an independently received
CETA public-key fingerprint to establish the publisher identity.
The live showcase returns HTTP 200, and its download route redirects to this
exact 0.3.2 installer with no-store caching. The normal 0.3.2 update-client
functions fetched the signed live manifest and downloaded the verified installer.
That check used 0.3.1 as the comparison version; it did not execute the old client
or run a live GUI download-to-install sequence. Installed upgrade behavior was
validated separately in the offline Sandbox.

A fresh offline Sandbox verified 0.3.1-to-0.3.2 installation, actual version
window titles and frozen executable hashes, startup, uninstall and exact
synthetic conversation/message/draft/preferences preservation. SQLite schema 1
is unchanged; this is compatibility evidence, not a schema-version migration.
The owned Sandbox was stopped and no other Sandbox was stopped by the test.
The preserved 0.3.1 updater still has the HTTP 403 issue; its users must manually
install 0.3.2 to obtain the fix. No model or inference validation is added here.

`evidence/CETA_DESKTOP_PUBLICATION_032.json` binds the actual reports and retains
the distinct 0.3.1 visual-design checkpoint. The separately authorized website
audit and its unpublished backlog remain separate, preserved work. The reference
training dependency gate for Transformers 5.5.0 / CVE-2026-9856 remains unresolved
and requires its own compatibility follow-up. Earlier evidence was not rewritten.

## Desktop 0.3.3 icon repair: source and compiler checkpoint

The exact published 0.3.2 installer contains seven generic NSIS icon frames and
no 256-pixel frame. Its application executable contains CETA artwork, but only
one 256-pixel DIB frame. This is an embedded-resource defect, not merely a shell
cache explanation. The read-only baseline is retained outside the repository at
`C:\Users\Quencher\.codex\audits\CETA-icon-release-20260906\CETA-0.3.2-ICON-BASELINE.json`,
SHA-256 `bceeadc329ad9f05877c97cd38dca2dd422bfd44aceaf06bd18ba1585de5fa41`.

The 0.3.3 source renders the existing CETA SVG at 16, 20, 24, 32, 40, 48, 64, 128
and 256 pixels. Small frames use 32-bit DIBs with AND masks; 256 uses PNG.
`MUI_ICON` and `MUI_UNICON` are defined before the installer pages, and the shell
DisplayIcon and shortcut explicitly select CETA.exe icon index 0. Compiled-resource
checks reject default, missing, extra or mismatched artwork and require all nine
frames. The `!uninstfinalize` gate validates the uninstaller before embedding;
the built application and installer receive separate checks.

The coordinator's focused run passed 26 tests (11 icon and 15 signing) in 1.481
seconds; Ruff F/E9 passed. The actual NSIS 3.12 compiler preflight validated the
synthetic installer and generated uninstaller under the external audit directory's
`nsis-preflight-001`. The synthetic installer was not executed. This is compiler
and source evidence, not a released 0.3.3 application.

Build 006 subsequently stopped at its desktop test gate: 130 tests ran in 54.779
seconds, with one failure and one host short-alias skip. The failure was
`test_workload_exit_and_persistence`: workload_id remained set when the test
expected completion. The failed result/log are preserved in the same external
audit directory. This blocks that build attempt and requires focused diagnosis
and a fresh successful build; no 0.3.3 real-binary or publication success is
claimed at this checkpoint. The public 0.3.2 release and earlier evidence remain
unchanged.

## Desktop 0.3.3 icon repair: verified build and installed resources

Source commit `4e51cbf2b13d64da4b6007e8fac6761833b0fc72` retains the existing CETA
SVG while supplying nine icon sizes and enforcing matching PE resources in the
application, installer and generated uninstaller. Read-only publication proof
matched all 275 committed files, 273 package payloads and 274 checksums. The
original curriculum branch, its five dirty core files and separate original
manifests were preserved.

Build 007 passed: 130 desktop tests ran, 129 passed and one host short-alias case
was skipped in 28.672 seconds. Windows CI passed all 130 tests in 49.909 seconds
and CodeQL passed. The earlier Build 006 workload-completion failure is preserved;
the separate GUI rerun passed all 16 tests in 13.174 seconds before the fresh build.

A fresh offline Sandbox verified the 0.3.2-to-0.3.3 upgrade and exact CETA artwork
in all 27 frames of the application, installer and actual installed uninstaller,
including the PNG 256-pixel frames. Shortcut and uninstall-list icon metadata
point to CETA.exe index 0. Startup, uninstall, synthetic conversation/draft/settings
and unknown-file preservation passed. The owned Sandbox was stopped.
The six public release assets passed unauthenticated hash and signature checks,
and the live site serves the exact 0.3.3 download and signed update channel.
The same installed 0.3.2 GUI verified the new release, downloaded it, handed off
to the installer after closing, and installed 0.3.3. An explicit installed Start
Menu shortcut action then relaunched 0.3.3 with the synthetic data and draft intact.
Automatic relaunch is not implemented.

This live cycle passed after normal Windows TLS initialization. In the fresh
Sandbox, first manifest discovery and first GitHub download failed certificate
verification. Ordinary validated Windows HTTPS GET/HEAD requests initialized the
missing public roots; unmodified GUI retries then succeeded. No manual certificate
import, validation bypass or application patch occurred. Pristine first-attempt
TLS success remains unverified and requires follow-up.

The icon proof concerns RT_ICON/RT_GROUP_ICON resources. The stock NSIS MUI
welcome-panel computer illustration remains as a separate, nonblocking visual
limitation. It is not part of the executable icon resource claim.

`evidence/CETA_ICON_PUBLICATION_033.json` binds these additive results. Personal
Ed25519 verification remains separate from Windows CA trust; no Explorer cache
refresh, schema-version migration, model inference or training validation is
claimed. The separate Transformers dependency failure remains unresolved.

## Reference dependency repair: September 7, 2026

The baseline main commit `ed389290c58d5fa8729f67a23fff674c5c73ecc0` failed
reference workflow run `34076668350`, job `101604017729`, at pip-audit:
Transformers 5.5.0 / CVE-2026-9856. The subsequent Ruff, reference verification
and package verification commands did not execute. The fix pins Transformers
5.10.1 consistently in the project, requirements, lock, bootstrap assertion and
dependency consistency test. Version 5.10.0 was withdrawn; 5.10.1 is the first
non-withdrawn fixed replacement. No other locked package version changed.

The isolated Python 3.12.10 Windows environment passed pip check and pip-audit
with no known vulnerabilities, including after adding the already-pinned desktop
and build extras needed for Windows resource tests. Ruff F/E9 passed across
src, scripts, tests and examples. The 18 existing language tests passed; two new
offline CPU compatibility/security tests passed in 2.726 seconds with no skips.
They exercise tiny synthetic Qwen3/LoRA optimization, actual CETA collation,
checkpoint resume, local serialization/reload and bounded generation, plus
chat-template path traversal rejection. They restore their random states and
block network connections. No pretrained model was downloaded or H100 run made.

The first local reference attempt ran 307 tests in 30.481 seconds and failed
four Windows-only icon tests because the reference-only environment lacked
PyInstaller; 48 tests skipped. This was an environment/dependency issue, resolved
by installing the existing locked desktop/build extras without changing the
Linux reference workflow. The fresh Windows run passed the complete verification
component sequence in 202.046 seconds: 307 tests ran in 148.083 seconds, 306 passed
and one host short-alias case skipped. The hostile epoch, recorded readiness,
continuation, final-heldout and runtime-demo verifiers all passed afterward.

Only the hostile gate's report destination was redirected to external audit
storage during local execution. The tracked report remains byte-preserved at
SHA-256 `975040abf1b61beeeff2d2a7a9826691f203208869afadbd8f35df953957ce5c`.
The unmodified workflow must be checked on the resulting GitHub commit; local
component validation alone does not establish a green remote package gate.
Reports and failed attempts are retained outside the repository under
`C:\Users\Quencher\.codex\audits\CETA-reference-dependency-20260907`.

Codacy's dependency scan returned no findings. Scoped source analysis retained
existing test-style findings and nonblocking notes on the new test, including a
managed-context false positive; no security bypass or suppression was added.
The baseline SonarCloud security-rating failure remains a separate gate requiring
review: four TLS findings conflict with verified Python secure defaults; other
findings concern local operator-selected paths and potential signing-CLI hardening
before any future untrusted-agent use. No Sonar issue was dismissed.

Historical H100 versions, hashes and promotion results are preserved. CPU API
compatibility does not establish H100/bf16/4-bit or numerical reproducibility
under the new dependency; upstream causal-LM loss counting changed. Original
dirty core files and separate original integrity manifests remain preserved.
The work is confined to CETA; no website, other repository, desktop release
artifact or application-version change is included.

### Linux CI follow-up: Windows protocol test fixtures

The first repair commit `f14aee57bb55a0bef35dc498d40afc03e7e76ef3` reached
reference run `34092195782`, job `101647860878`. Pip-audit reported no known
vulnerabilities and Ruff passed. The 307-test Linux run then stopped with seven
error records across two mocked signature-query methods (one method plus six
subtests), 66 skips, in 22.458 seconds. Each error was `KeyError: 'SystemRoot'`:
the fixtures mocked PowerShell results but relied on the host Windows environment.
The later reference components and package verifier did not execute in that run.

The two protocol fixtures now supply their own isolated synthetic SystemRoot and
assert the exact PowerShell executable path, retaining all literal-path and
incomplete/duplicate-response assertions. The real Windows integration test and
production signing implementation are unchanged. All 15 signing tests passed
locally in 10.370 seconds; the two mocked methods also pass with the surrounding
environment empty. This fixes test portability while retaining Linux coverage.
The subsequent commit requires its own complete reference CI result.

### 2026-09-14: Desktop architecture decomposition and test coverage enhancement

A complete snapshot of the repository and implementation plan was created prior to
execution (tag `snapshot-20260914-pre-implementation`, branch `snapshot/20260914-pre-implementation`,
and standalone archive `ceta_snapshot_20260914_pre_implementation.zip`).

Changes implemented:
1. **Shared component extraction**: Extracted `button`, `action`, `page`, `card`,
   and `filter_list` into `src/ceta_desktop/components.py`.
2. **Page decomposition**: Created modular page widgets in `src/ceta_desktop/pages/`:
   `WorkloadsPage`, `SettingsPage`, `UpdatesPage`, and `LibraryPage`. `MainWindow` in
   `src/ceta_desktop/app.py` was refactored to delegate to these pages while retaining
   attribute properties and delegators for 100% backwards-compatibility.
3. **Storage & UX features**: Added `Store.delete_conversation` and `Store.rename_conversation`
   in `src/ceta_desktop/storage.py`, with UI actions in `_chat_page` rail and `LibraryPage`.
4. **Testing gap coverage**: Added 10 targeted test cases in `tests/test_desktop_backend.py`
   and `tests/test_desktop_gui.py` covering: future schema rejection, version zero DB
   creation, 4 MiB exact boundary & overflow rejection, GGUF v2/v3 header checks & invalid
   rejection, disk space failure handling, path traversal vectors, 120s socket deadline,
   and conversation deletion GUI workflow.
5. **Developer documentation**: Added `CONTRIBUTING.md` and `docs/DESKTOP_ARCHITECTURE.md`.
6. **CI/CD & integrity**: Added `--check` mode to `scripts/build_package_manifest.py` and
   `scripts/build_sha256sums.py`, and wired manifest check step into `.github/workflows/desktop.yml`.
7. **Formal verification**: Added INV-010 (state transition determinism) and INV-016
   (nonce consume counter monotonicity) bounded model assertions to `scripts/run_bounded_models.py`.
8. **Performance**: Optimized workload stdout buffering in `MainWindow` using chunk lists.

Validation results:
- Desktop test suite: 140 tests ran in 58.194 seconds, 139 passed, 1 skipped (host short-alias case).
- Bounded model checker: passed (`states=9 transitions=12 max_depth=4`).
- Ruff (F, E9) and `network_boundary.py`: passed cleanly with 0 errors.
- Package manifest: verified pass (`PACKAGE VERIFY: PASS`, 283 registered payload files, root hash matching).

### 2026-09-19: Claims repair and hardware-aware local model selection

Authorization: the user requested concrete claim/implementation repairs across
CETA, its native desktop, and governed runtime/verification, then clarified the
product goal as an offline local assistant whose model choices reflect the
hardware of whichever computer installs it. They explicitly prohibited treating
the development computer's GPU/RAM as repository defaults. Work remains in
`T:\00-Active\CETA-desktop-delivery-20260906`, branch
`codex/ceta-desktop-release`, based on clean HEAD
`7ebabf903c109d35c6cb7065ee68dd4f7d151b80`. No other project's source, models,
data, evidence, or branding was imported. Installed shared tools and the existing
declared Ollama runtime were used; no publication or signing was performed.

Implemented:

- The Models page inventories the running computer on demand and refreshes
  availability before assessed downloads, GGUF starts, and Ollama inference.
  Physical RAM, logical CPUs, NVIDIA free VRAM, and native Windows DXGI dedicated
  capacity/process budgets are distinguished. Shared memory and multiple GPUs are
  not pooled. Unknown readings remain unknown. Profiles live in memory only;
  no actual host specification is distributed as an application default.
- Explicit model tags have approximate download sizes and conservative working
  memory estimates at 4096 context tokens. Suggestions only fill a download name;
  downloading remains explicit. Larger memory permits larger candidates, without
  treating capacity as a model-quality or speed benchmark. Preloaded same-model
  residency is checked separately to avoid counting its weights twice.
- Ollama model metadata is checked before transmitting conversation text.
  Cloud-backed names and remote aliases are excluded/rejected. Other local
  OpenAI-compatible services remain labelled as having unverified inference
  locality. One short synthetic probe reports actual text/elapsed time and
  runtime-reported allocation; estimates alone cannot produce a verified result.
- Stale hardware suggestions are cleared on scan failure, chat/probe concurrency
  is blocked, model/endpoint changes invalidate displayed readiness, and normal
  Ollama requests enforce the same 4096 context bound. CETA-started Ollama limits
  model residency and request parallelism to one. Models controls remain reachable
  at 1100x720 and 1540x940; visual QA used synthetic profiles.
  Delayed model-discovery success/failure from an earlier endpoint cannot replace
  the current endpoint's model list or connection status. Reopening the same data
  directory on different synthetic hardware recomputes recommendations and restores
  no old hardware profile or readiness claim while retaining user data/model choice.
- Conversation deletion atomically removes its own draft/settings, cancels the
  old draft timer, and restores the surviving conversation's separate draft.
  Unavailable editor recovery drafts survive normal application closure.
- Durable authority operations hold thread/process locks over validated refresh,
  append, fsync, and projection. Stale instances cannot double-consume a permit;
  live readers reject observed-history regression. Paths bind to their canonical
  location. The persistent `.lock` sidecar coordinates cooperating processes.
- Adapters require a signed, live, single-use gateway dispatch. Captured calls
  cannot replay after completion, errors, restart, or concurrent/reentrant use.
  Observer public-key bytes must differ from all trusted executor keys, including
  when identities or key labels differ.
- Verification writes new exclusive report files instead of overwriting historical
  hostile-gate evidence. The runner is import-safe and stops without printing PASS
  when any component fails. STATUS now distinguishes the CPU smoke result from the
  H100 result and names the currently pinned Transformers version accurately.

Baseline failures were reproduced before repair: deleted drafts crossed
conversation boundaries, an unavailable recovery draft disappeared on close,
two stale ledger instances consumed the same permit, a captured signed invocation
repeated an effect, and an executor key was accepted under an observer alias.
Regression tests now exercise these failures plus unknown/insufficient memory,
multiple synthetic hardware profiles, cloud aliases, incomplete generation,
resident models, cancellation, and report-output preservation.

Validation records for this work are separate from historical release evidence.
The completed full run is under `build/claims-validation-20260919-a55c1688651c432b8b7ff5ee63c5112e/`.
The existing hostile report
remains bound to SHA-256
`975040abf1b61beeeff2d2a7a9826691f203208869afadbd8f35df953957ce5c`.

Discovered issues and limits:

- Fixed now: initial sandbox Python-launch denial was resolved by executing this
  checkout's existing interpreter with approved filesystem access. Missing declared
  training/test extras were installed from the unchanged lockfile in this checkout.
- Environment/dependency issue, blocking a clean training dependency audit:
  `accelerate==1.14.0` is reported under `PYSEC-2026-3804` / `CVE-2026-69112`, with
  no fixed version supplied by the audit. The issue concerns checkpoint index
  `weight_map` path traversal and special-file loading; see the
  [upstream report](https://github.com/huggingface/accelerate/issues/4067) and
  [PyPA advisory](https://github.com/pypa/advisory-database/blob/main/vulns/accelerate/PYSEC-2026-3804.yaml).
  No advisory was suppressed and no unsupported upgrade was represented as a fix.
  The separately exported locked desktop dependency closure passes pip-audit;
  Accelerate is not part of that closure. Follow-up requires a verified upstream
  fix or a reviewed loader-boundary repair, then language compatibility tests and
  a fresh unsuppressed audit before training-release readiness can be claimed.
- Resolved environment issue: a real local validation model was downloaded explicitly
  through Ollama (`qwen3:0.6b-q4_K_M`, 522653767 bytes). Its first inference attempt
  was rejected before loading when available RAM fell below the estimate.
  That first attempt is a verified refusal, not successful inference. Its installation
  and probe records are external at
  `T:\Temp\ceta-local-readiness-20260919-eob0mwg9`; no host readings were saved as
  product configuration. The OS network was not disabled for these checks.
- Not claimed: production safety certification, resistance to an attacker
  replacing all ledger state before a fresh start, arbitrary service offline
  enforcement, quality/speed guarantees, hardware-backed authority, a new H100
  epoch, or a newly built/published installer. Source changes require their own
  release build and installed lifecycle validation.

Completed validation:

- `python scripts/verify_all.py --hostile-report <new-output>` passed all 18 stages,
  including 412 unit tests in 177.578 seconds (411 passed, one Windows short-alias
  case skipped). Slow first imports of newly installed Torch dependencies caused
  a long discovery delay; read-only diagnostics confirmed forward progress.
  The hostile gate passed 11 checks over 1380 cases. Its new report hash is
  `sha256:10524483f0d023d9c6c3c3c483dd3c1f859d85b8776417b118704e8e15fe96f7`.
  Historical epoch/heldout reports were verified, not regenerated or retrained.
- Final model transport regressions: 25 passed. After the endpoint race repair,
  the hardware UI suite passed 10 tests, including the different-computer restart
  regression. Native Windows inventory tests passed 13 cases; integrated hardware,
  DXGI, and UI checks passed before the final two UI regressions were added.
- Repository-wide `ruff check --select F,E9 src scripts tests examples` and
  `git diff --check` passed. `pip check` passed. The separately exported locked
  desktop dependency closure passed its unsuppressed `pip-audit`; the full training
  dependency audit still reports the Accelerate issue above.
- After the verification workload released memory, the unmodified memory guard
  allowed `qwen3:0.6b-q4_K_M`. A real synthetic probe returned `CETA_READY` in
  47.203 seconds, with runtime-reported CPU residency and 4096 context tokens.
  Its record is `T:\Temp\ceta-local-readiness-final-11zbaslr\probe.json`.
- `python scripts/verify_desktop_inference.py --endpoint http://127.0.0.1:11434/v1
  --model qwen3:0.6b-q4_K_M --output <new-external-directory>` passed: native chat
  returned `LOCAL_OK`, marked both messages complete, and retained identical
  conversation contents after reopening. Elapsed chat time was 53.672 seconds.
  Records and screenshot are at
  `T:\Temp\ceta-native-inference-final-56a3328b30de4db1a4a554f79778ffe5`.
  Both actual runs are integration checks, not quality/speed benchmarks or proof
  of OS-level network isolation. No hardware measurement became product defaults.
- Source package manifest and SHA256SUMS were regenerated and passed their
  `--check` modes and `python scripts/verify_package.py` (293 registered payload
  files). Final documentation changes are included by regenerating/checking the
  same hashes again. This is source-package integrity, not an installer build.

## 2026-09-19 — CETA + Model 001 merger implemented

Mode: implementation and local release-candidate validation. User request:
"implement the plan pleaser and thank yuu"; this lifted the prior CETA read-only
restriction for the approved merger. Source was selected Project-AI Model 001
components; destination was this existing CETA delivery checkout. The original
CETA checkout, Model 001 source, other projects, publisher keys and host user
databases were preserved. HEAD remains 7ebabf903c109d35c6cb7065ee68dd4f7d151b80;
existing dirty work was retained and no Git publication occurred.

Created: the shared journal and owner adapters, task runtime, project tools,
provider interface, DPAPI runtime identity, internal ceta_model001 integration,
historical-only importer, task UI, migration/package/role/hostile regressions,
release runner and packaged synthetic verification. Modified: actual desktop
call sites/storage/archive behavior, existing release/CI/configuration/docs and
focused legacy tests. No source files deleted, moved or renamed.

Verified: full 18-stage gate with 564 tests (one short-alias skip), isolated desktop
release gate with 475 tests (one skip), unsuppressed desktop dependency audit, pip check,
Ruff F/E9, extracted-wheel real edit/restart, actual frozen workflow/migration,
one live installed local-model request through merged reviewer/context/history,
and offline Windows Sandbox 0.3.3-to-0.4.0 install/update/restart/uninstall with
synthetic legacy/unknown data and checkpoint preservation. Historical hostile
reports were not overwritten. The source transfer manifest hashes were verified.

Result: unsigned CETA 0.4.0 local release candidate. Installer SHA-256:
ddea9a61ae6951136493bf22db81401fe6b98c0ba2187a668960e40a77c5eef2.
No production, public signing, online update or website deployment claim.
Commands remain explicitly trusted local execution; local history has no external
rollback anchor. The recorded training Accelerate audit and initial public TLS
trust setup issues remain separate follow-ups. One unrelated duplicate desktop
page method in HEAD was classified nonblocking and preserved.

Full changed surfaces, commands, repaired failures, evidence paths, artifact facts
and limits: docs/operations/MERGER_IMPLEMENTATION_20260919.md and
evidence/CETA_MODEL001_MERGER_20260919.json. Source package manifests are refreshed
and checked as the final delivery step after this entry.
