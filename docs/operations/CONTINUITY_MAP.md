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

## 2026-09-25 — Dependable offline product plan

Mode: planning, current-source audit, and documentation delivery. The user asked:
"Plan it out with extreme prejudice and get this infota better than this."
The plan carries forward their explicit requirement that CETA inspect each
installing computer, rather than ship the developer's GPU/RAM as defaults.

Current root/branch: `T:\00-Active\CETA-desktop-delivery-20260906`,
`codex/ceta-desktop-release`, clean baseline commit
`aadbeb1aff74118e6042cd5194268ebba6d18e28`. Desktop version 0.4.0 and retained
reference version 0.3.0 are intentionally separate. Current code, tests, release
scripts and dated merger evidence were inspected; historical test/installer
results were not rerun or relabeled as current qualification.

Created: `docs/operations/CETA_OFFLINE_PRODUCT_PLAN_20260925.md`, with 16
source-grounded findings, 13 work packages, four delivery milestones, exact
implementation surfaces/dependencies, failure-state contracts, an adversarial
acceptance matrix, hardware/offline qualification and release gates. Three
independent read-only reviews checked onboarding/daily use, hardware/backend
correctness, and release/evidence boundaries. Their corrections are incorporated,
including preparation before chat admission, chronological prompt ordering,
task renewal/reconciliation, identity-loss recovery, uncertain backend cancellation,
mutable-model identity, and qualification of the final exact artifact bytes.

Priority findings are planned repairs, not fixes performed in this turn: saved
24-hour task grants lack an explicit renewal flow; assembled prompts lack combined
input/output token admission; pasted file attachments omit path-based instruction
compilation; GPU fit is not bound to runtime compatibility/device selection;
missing runtime identity can create new keys beside existing history. Other
findings cover model switching, cancellation/concurrency, setup, archive retrieval,
responsive inspection, and current release documentation. Each is assigned to a
work package with reproducing tests required before implementation.

Project boundary: no additional source/assets/models/data were imported from another
project. The already integrated Model 001 components were read only as existing
CETA source. No source-code, dependency, user-data, runtime, installer, signing,
website or publication change was made. Only the plan, this continuity entry and
derived source package manifests/checksums are in the planned changed-file set.

Validation scope: current root/commit/clean baseline checked; source call sites
reviewed; plan local links and whitespace checked. Full unit, inference, installer,
offline, hardware and dependency-audit suites were not run in this planning turn.
Source-package integrity checks for the documentation delivery are distinct from
the future product qualification described by the plan.

Documentation delivery checks passed: three local plan links resolve;
`git diff --check` is clean; `build_package_manifest.py --check`,
`build_sha256sums.py --check` and `verify_package.py` pass after regeneration
(330 registered payload files). The final note is included by regenerating and
checking the same manifests again. Expected modified set: this continuity map,
the new plan, `PACKAGE_MANIFEST.json`, and `SHA256SUMS` only.

## 2026-09-27 — Dependable offline product implementation begins

User objective: "Implement the dependable offline product described." The full
September 25 plan remains the objective; this is the renewal/recovery increment,
not completion of the full product. Root remains this CETA checkout, branch
`codex/ceta-desktop-release`, HEAD `aadbeb1aff74118e6042cd5194268ebba6d18e28`.
The existing plan/continuity/manifests were preserved. No new cross-project
source, assets, model weights, conversations, credentials or evidence imported.
No commit, push, build, signing or public release was performed.

Implemented: explicit expired-grant renewal and distinct revoked reauthorization;
same-task/history preservation; invalidation of prepared context after a grant
change; draft-preserving expired chat rejection; visible startup/interrupted task
recovery; project-wide uncertain-effect blocking; append-only reconciliation
observations without replay or false effect certification; read-only startup
identity/database checks before normal writes; a native preserved recovery view
with unverified conversation export; exact source/interpreter/test/skip attribution
in the desktop verification report. Current release documentation now distinguishes
public 0.3.3 from the historical unsigned local 0.4.0 candidate and current work.

Evidence: baseline 71 tests passed; new regressions reproduced the actual gaps;
final focused recovery/native/verifier suite 34 passed; touched-file Ruff F/E9
passed. Final full desktop/runtime gate: **497 run, 496 passed, one skip**, zero
failures/errors, unchanged tested source hash. The skip is the unavailable distinct
Windows short-path alias on the temporary volume. Report:
`evidence/CETA_OFFLINE_RECOVERY_FINAL_20260927.json`; earlier passing report retained.
Synthetic native controls were visually checked in
`evidence/CETA_OFFLINE_RECOVERY_UI_FONTS_20260927.png`. The offscreen renderer's
initial zero-font discovery was resolved in the test process by loading the
existing Windows font, without changing product/host font settings.

Failures classified and repaired: uv Python launch sandbox restriction and initial
missing PYTHONPATH were environment/command issues; new fixture double-close and
SQLite cleanup errors were corrected; newly reproduced product recovery failures
were repaired. Windows short-alias coverage remains an environment limitation.

Full changed surfaces, commands, exact validation scope and the complete W00-W11/WT
remaining-work matrix are in `docs/operations/CETA_OFFLINE_IMPLEMENTATION_20260927.md`.
Next: W01 combined request budgeting and attachment provenance, then W03/W04
backend/resource binding and runtime coordination. Managed setup, capability
qualification, archives/responsiveness, installed real-model offline testing,
candidate/lifecycle/public delivery and training advisory repair all remain in
scope. The active goal must not be marked complete based on this increment.

Source-package validation passed after registering the new files: manifest builder
`--check`, SHA256SUMS builder `--check`, and `verify_package.py`, with 338 registered
payload files. Final record edits are included by regenerating and checking the
same derived files again. These hashes are source integrity, not release proof.

## 2026-09-27 — Prepared requests and implementation status

Continued the existing user-authorized dependable offline product implementation
in `T:\00-Active\CETA-desktop-delivery-20260906`, branch
`codex/ceta-desktop-release`, baseline `aadbeb1aff74118e6042cd5194268ebba6d18e28`.
Preserved the dirty W02 work, planning documents and historical reports. No new
cross-project transfer, model download, signing, publication or release occurred.

Implemented W01 source surfaces: asynchronous preparation before draft/transcript
admission; attachment path/disk/editor provenance and nested instructions; paired
chronological history with the current user last; combined estimated input/output
allocation and explicit omission review; recorded single-attempt prepared payloads
with source/grant/runtime revalidation at dispatch; transactional chat admission;
retry restoration without duplicate user turns. Native request preview displays
the outgoing payload. The advanced profile explicitly labels its estimate as
unverified: exact tokenizer/bound and immutable backend identity remain W03 work.

Related repairs: readiness probes now execute the recorded prepared messages;
generic empty/malformed completions fail; admission preserves cancellation flags;
terminal generation checks authority freshly, even inside the polling interval.
New tests live in `tests/test_generation_plan.py` and
`tests/test_desktop_requests.py`; existing runtime/native tests were updated for
the intended request contract. The public message API remains compatible, with
sequence identifiers available through an explicit option for retry handling.

Validation before the final full gate: 23 focused request tests, an integrated
64-test runtime/UI/journal suite and a 62-test request/provider/backend suite
passed. Initial full gate `evidence/CETA_OFFLINE_REQUESTS_20260927.json` ran 520
tests with four failures and one environment skip. Two hardware probe fixtures
were updated for serializable metadata/prepared-request arguments. Two failures
exposed the terminal authority polling defect; the source repair passes tests
with a fixed monotonic clock. All four focused regressions now pass. These
failures are classified fixed now; the failed report remains intact. Final gate
`evidence/CETA_OFFLINE_REQUESTS_FINAL_20260927.json`: **520 run, 519 passed,
one environment skip**, zero failures/errors; unchanged source SHA-256
`eedf574eef6fbaa0976ba65a2431c4d863443a2ff48ee22a3d978c5a1597765f`.
The skip is the unavailable distinct Windows short alias on the test volume.
Touched-file Ruff F/E9 and `git diff --check` passed.

Visually inspected `evidence/CETA_OFFLINE_REQUEST_UI_20260927.png`: synthetic
captured attachment and retained composer with an explicitly unverified budget;
no inference performed. Existing Windows font loaded only in the test renderer.

In response to the user's implementation-status question, current source inspection
confirmed per-computer RAM/GPU discovery and no saved hardware readiness at window
creation. This is partial implementation, not a complete hardware-qualified offline
product. Backend/device/resource binding, managed setup, measured capabilities,
installed real-model offline tests and candidate delivery remain open. The next
implementation packages are W03/W04. The overall goal remains active.

Source manifest/checksum regeneration, both `--check` modes and
`scripts/verify_package.py` passed with 344 registered payload files; the same
checks are repeated after these final record updates. This verifies source
integrity only. No commit, push, installer build or installed inference validation
was performed for the request-preparation increment.

## 2026-09-27 — Backend-specific resource admission

Continued the active dependable offline product goal in the same CETA checkout,
branch `codex/ceta-desktop-release`, baseline `aadbeb1aff74118e6042cd5194268ebba6d18e28`.
The preceding goal turn was progress: prepared requests/recovery were implemented
and source-verified. Preserved that dirty work and its evidence. No new project
content or hardware defaults were imported into CETA.

Implemented the F04/F05 admission repair in new `src/ceta_desktop/backends.py`,
native model startup, Ollama preflight and provider receipts. Owned GGUF startup
inspects the selected executable/version/options/devices, verifies the model,
reads bounded metadata and samples the executing computer's hardware. A GPU plan
requires an unambiguous dedicated device supported by that executable; a separate
CPU plan disables GPU/KV/operation offload. Unknown RAM cannot start a model. No
GPU pooling or addition of shared RAM to dedicated memory is permitted.

Launch receipts bind the executable/model hashes, environment identity, device,
memory components and actual arguments: one slot, 4096 context, explicit device,
cache/offload/batch and fit controls. Runtime inspection is a registered governed
application operation. User cancellation, stale inspection or changed executable,
environment, model selection or endpoint rejects launch. The Stop control cancels
inspection. Process error/exit clears its active launch plan. Runtime inspection
uses bounded output/time and kills only its own child on cancellation/deadline.

External Ollama no longer uses an unrelated GPU estimate to approve a load that
does not fit measured RAM. Resident reuse requires matching nonempty digest and
context plus RAM headroom; it does not prove quiescence or controlled placement.
Memory metadata/size join request identity checks; resource observations are
included in provider results. All memory estimates remain explicitly unverified.

Validation: initial 49 tests had one new assertion using the wrong existing
journal field path; repaired to `consequence.arguments`. Integrated 87 tests passed.
Additional 25 focused tests passed; Ruff found duplicated new test methods, which
were removed without dropping distinct cases. Touched-file Ruff then passed.
These introduced fixture/edit problems are classified fixed now. The final full
gate is saved as `evidence/CETA_OFFLINE_BACKEND_ADMISSION_20260927.json` and its
completed result is recorded below.

Installed-backend inspection: standard local Ollama client reports version 0.34.3;
no running service was reachable and `/api/version` returned connection refusal
10061. Environment/runtime unavailable, not blocking source work. No service was
started or modified and no model loaded/downloaded. This is not live API or
inference qualification. Official llama.cpp CLI/device-output sources were checked;
the selected executable must separately pass its actual option/device inspection.

Remaining: W03 exact tokenizer/immutable managed asset/runtime qualification;
W04 owned endpoint identity/health, shared leases and uncertain cancellation;
then the unchanged setup, capability, offline/install/release and training work.
The full goal remains active. Detailed implementation, tests and limitations are in
`docs/operations/CETA_OFFLINE_IMPLEMENTATION_20260927.md`.

Completed full gate: **537 run, 536 passed, one environment skip**, zero failures
or errors. The skip remains unavailable distinct Windows short-path alias coverage.
Tested source was unchanged during the suite and all 207 attributed files matched
afterward; source SHA-256
`edc6ded1ce6817a8a99c8419ac26fed680df4d0269cb742b7285e507c532bc1d`.
`git diff --check` passed. Source manifests/checksums are regenerated and verified
after final record edits. No commit, push, new installer, signing or public release.

## 2026-09-27 — Shared runtime leases and uncertain dispatch

Continued the active goal in the same CETA checkout/branch/baseline. The previous
turn was verified progress on backend admission. Existing dirty work and all prior
evidence were preserved; no cross-project material was transferred.

Added `src/ceta_desktop/runtime_coordination.py`: OS-released endpoint locks shared
across cooperating same-account CETA processes, normalized loopback aliases and
prefixes, durable pre-dispatch state and uncertainty across cancellation/crash.
Terminal protocol observations clear a completed dispatch; a released lock does
not clear unknown backend activity. Windows PID creation time and accepted TCP
connection ownership are observed; unsupported/inaccessible identity stays unknown.

Integrated leases with real transport and preparation checks, bounded HTTP connect,
write/read cancellation and absolute deadlines, provider result observations,
native stopped-output messaging and governed **Recheck runtime** observations.
A client-operation guard also prevents overlapping providers from corrupting one
client's active request state. Recheck cannot certify separate model workers ended
merely because the original server process exited. That observation is retained
without clearing uncertainty. Owned containment/health/restart remains necessary
to make recovery usable; this increment must not be presented as all of W04.

Validation: existing transport/readiness/request 44 passed; integrated 52 passed;
native/request/merged-runtime 75 passed. Initial new native fixture incorrectly
expected the uv launcher PID; the query correctly found the child interpreter.
The fixture now starts the base interpreter. Two first full-gate failures came
from new fixtures depending on live host RAM; synthetic memory fixes them.
A separate reproduction exposed the same-client terminal-observation race; the
guard and regression repair it. These issues are classified fixed now.

Final focused coordination suite: 13 passed; touched-file Ruff F/E9 passed.
Preserved failed full report `evidence/CETA_OFFLINE_RUNTIME_COORDINATION_20260927.json`
(551 run, two failures, one skip). Final report:
`evidence/CETA_OFFLINE_RUNTIME_COORDINATION_FINAL_20260927.json`, **552 run,
551 passed, one environment skip**, zero failures/errors. The skip remains the
unavailable distinct Windows short alias. All 209 attributed source files match;
source SHA-256 `764effcf845f3b83be213ea122f804561b94fb1404d717a7b39194b5a5e919ca`.
`git diff --check` passed. Source manifests/checksums are refreshed and verified
after final documentation edits; no installer/build/signing/publication occurred.

Visual diagnostic `evidence/CETA_OFFLINE_RUNTIME_COORDINATION_UI_20260927.png`
shows the new runtime control but clipped hardware-description labels. This is
not a visual pass. Classification: requires follow-up UI repair before UI/release
qualification. Temporary synthetic data and the existing Windows font were used;
no host hardware profile was made a product default and no model inference ran.

Next work: owned process-tree containment from launch through confirmed shutdown,
owned endpoint health/identity and restart-based cancellation recovery; repair the
observed label clipping. Resident model switching/unload, non-HTTP deadline stages,
tokenizer/managed asset qualification and the original setup/capability/offline/
release/training packages remain open. The full goal stays active.

## 2026-09-27 — Owned Windows runtime lifetime and status review

Answered the implementation-status question by checking this checkout, source and
evidence. The fourth-increment report's 209-file source digest exactly matched
before editing. The full offline product is partially implemented, not completed.
Continued the existing active goal on `codex/ceta-desktop-release`, same baseline
`aadbeb1aff74118e6042cd5194268ebba6d18e28`. Dirty work and historical evidence were
preserved. No additional cross-project material or host hardware defaults entered
the product.

Added Windows job lifetime control and a Qt adapter for the model runtime only.
The runtime starts suspended, is assigned to a job without breakaway permissions,
and is durably registered before execution. Existing endpoint ownership and an
already-starting runtime prevent duplicate startup. Dispatch binds the actual
endpoint process to its saved job. Stop terminates job members; completion waits
for zero active processes, including when the root exits before its descendants.
An owner crash closes the job and ends its members. Recheck can use saved job
identity to recover an interrupted dispatch after restart, with uncertainty
retained on observation errors or live workers. Existing application start/stop
authority and observations remain the call path.

The manual flow is Stop local model, Recheck runtime, Start. HTTP/model health,
automatic restart, switching/unload, frozen-backend qualification and complete
deadline propagation remain open. This controls Windows job members, not brokered
or remote work or malicious executables; external services keep their uncertainty
limitations. Backend inspection subprocesses still need the corresponding child
lifetime qualification; classification: separate follow-up within the original
goal, using the same containment primitive in `backends._inspect_command`.

Validation so far: initial seven containment tests had two pipe-API unpacking
errors, corrected, then seven passed. GUI/merged-runtime and layout: 47 passed.
Owned/coordination checks: 24 passed. Extended native/crash/recovery and hardware
UI: 28 passed. Touched Ruff F/E9 and `git diff --check` passed. New fixtures use
temporary processes/data, never real model inference. The full gate result is
recorded after completion below.

The earlier clipped screenshot was isolated as an unsettled-layout measurement.
The new `evidence/CETA_OFFLINE_OWNED_RUNTIME_UI_DIAGNOSTIC_20260927.png`, rendered
with the existing Windows font and settled geometry, has readable descriptions.
Added geometry checks at 1100x720 and 1440x1080; no speculative UI edit or text
removal was needed. This limited visual check does not qualify the whole app.

No commit, push, new installer, signing or publication. W03 and the original
setup/capability/offline/install/release/training work remain in scope; the goal
stays active. See the implementation record for the current remaining-work matrix.

First full gate preserved as `evidence/CETA_OFFLINE_OWNED_RUNTIME_20260927.json`:
566 run, four fixture failures, one skip, zero errors. New and existing crash
helpers depended on inherited `PYTHONPATH`, so direct verification could not import
CETA in child interpreters. Each fixture now explicitly supplies this checkout's
source path. Corrected owned/coordination checks without inherited `PYTHONPATH`:
27 passed; Ruff F/E9 passed. Classification: fixture environment issue, fixed now.
The final attributed gate is rerun into a separate report.

Final gate: `evidence/CETA_OFFLINE_OWNED_RUNTIME_FINAL_20260927.json`, **566 run,
565 passed, one environment skip**, zero failures/errors. The temporary volume
does not provide a distinct Windows short-path alias. All 212 attributed source
files remained unchanged and match after the run; source SHA-256
`3c81e8b7d74e77efb2649b5e22e8a3b281a299f6696a577b1352a2253b851845`.
Source manifests/checksums are regenerated and checked after final record edits.
Git reports an inaccessible user-global ignore file; classification: environment
warning, not blocking repository status/diff checks. No global configuration was
changed. No new source/release completion is inferred from that warning or these
synthetic tests. The full offline product goal remains active.

## 2026-09-27 — Owned service health, restart and explicit resident unload

Classified the previous goal turn as verified progress and continued the original
objective in the same checkout/branch/baseline. Preserved all dirty/untracked work
and earlier evidence. No additional project content was transferred.

Owned Windows starts now trigger bounded background HTTP health/catalog checks,
bound to every accepted connection's process membership in the expected job.
Service health is distinct from inference/capability verification. Observations
are governed `model.inspect` actions tied to the start action; stale run/endpoint
callbacks cannot update current settings. Failed health stops owned workers.
An existing manual model choice survives catalog refresh even when unavailable.

Added explicit Restart owned runtime, which waits for job shutdown and repeats
startup admission/reconciliation. GGUF restart repeats file/runtime/hardware
preparation for the same selected pack. Stop/close/settings changes cancel queued
restart; failed stop and active local work prevent it. External services are not
restarted by this control. Non-Windows manual connection guidance is preserved.

Added resident-model inspection and explicit unload through registered
`model.unload` authority. Snapshots expire and bind endpoint/process/model digest;
actual dispatch rechecks identity under the shared runtime lease. The empty unload
request affects only the explicit selection; installed model files and the chosen
active model remain. Acknowledgment plus reported absence are required for that
unload's completion. Interrupted/invalid/unobserved unload remains uncertain, and
earlier uncertain inference blocks unload. External clients and mutable tags still
lack a server-side atomic compare-and-unload transaction. Fresh memory admission
is required on the next request.

Windows runtime inspection now contains child workers through the same job
primitive. The previously recorded inspection-child follow-up is fixed in source
and tested with an actual child surviving until the inspection deadline.

Validation: existing readiness/native/merged/hardware 87 passed; initial lifecycle
10 passed; lifecycle/unload/transport/coordination 56 passed; contained-inspection/
owned/lifecycle/hardware 58 passed. Touched Ruff F/E9 and `git diff --check` passed.
Native capture `evidence/CETA_OFFLINE_RUNTIME_LIFECYCLE_UI_20260927.png` was visually
inspected: new controls and hardware text are readable at settled 1440x1080. It
uses synthetic hardware/data and proves no model inference or full UI acceptance.

Added `scripts/verify_owned_service.py` and ran it against the installed Ollama in
an empty temporary profile/model store/coordination directory on a separate local
port. Child environment overrides did not change global configuration. Both
initial and final evidence reports are preserved. Final:
`evidence/CETA_OFFLINE_OLLAMA_SERVICE_FINAL_20260927.json`, two passed start/health/
stop cycles, version 0.34.3, distinct job identities, 14 total job-associated
processes per cycle, zero active members after stopping, ended-job recovery.
Executable SHA-256 `f282bab3cb8ece9f1843811c08e54fec449557efadc49ee0f9af07f1b93407fc`.
This is real service metadata/lifetime evidence, with no weights loaded/downloaded,
no inference, and no OS network isolation. It does not qualify GPU use or an
installed/frozen app. No existing user models or conversations were used.

Full source gate: `evidence/CETA_OFFLINE_RUNTIME_LIFECYCLE_20260927.json`, **583 run,
582 passed, one environment skip**, zero failures/errors. Skip: unavailable
distinct Windows short-path alias. All 214 source files remained unchanged and
rehash to the same digest as both the full suite and the final real-service run:
`d39e96aa44547c90a11b2fba39cd90a12b55937be8b15bee540bd6806ad3143c`.
Source manifests/checksums are refreshed and checked after final record edits.

Next: remaining whole-request hardware/context deadlines, real-weight lifecycle
qualification, W03 exact tokenization/immutable assets, then the original managed
setup/capability/archive/offline/install/release/training packages. The full goal
remains active. No commit, push, new installer, signing or publication occurred.

## 2026-09-27 — Managed runtime acquisition and native controls

The preceding status reply was no implementation progress. Revalidated the same
root/branch/HEAD and preserved all prior dirty/untracked work. Continued the full
offline-product objective by advancing W05/initial W06; no other project content
was transferred. Remaining deadline, tokenizer, model, capability and release
requirements were retained rather than replaced by this increment.

Added `runtime_installation.py`, a bundled `runtime_catalog.json`, and native
`pages/runtime_setup.py` controls. Registered `runtime.install`, `runtime.import`
and `runtime.inspect` application actions. `app.py` now supports explicit managed
runtime acquisition/start, while retaining the existing external-runtime path.
`build_desktop.py` includes the catalog, and dependency notices explain the optional
runtime and retained licenses.

Pinned official Ollama 0.34.3 Windows x64 archive: 1,460,962,639 bytes, SHA-256
`306ce9e81e3491d147f558e60d7a389499f244d10f71859c6e4e899241d1b4ae`.
Read official release metadata/license and downloaded the archive into ignored
`build/managed-runtime-qualification-v0343`. Verified all 82 extracted files
(1,929,045,302 bytes), including runtime libraries and license notices, and pinned
their checksums in the catalog. No model weights or personal runtime data were
used. Initial sandbox networking was denied; the approved scoped network command
succeeded. Classification: environment restriction, resolved for this work.

Downloads have an official-host redirect policy, exact resume ranges, size/checksum
validation, disk admission, process locking and explicit pause. Offline imports
copy to private staging and verify before publishing a version/digest directory.
Unknown files, existing versions and failed staging are preserved. No executable
is started by acquisition. Managed start rehashes installed bytes and refreshes
the executing computer's hardware. It uses private profile/model/temp directories,
port 11435, cloud disabled, and a small inherited Windows environment without user
model/GPU overrides or unrelated credentials. Health verifies the pinned version;
restart repeats checks. No developer hardware observation becomes a shipped default.

Validation:

- Initial acquisition tests: 15 passed. First combined native run: 53 run, one
  new-test error (journal field `operation` instead of `kind`). Corrected the
  assertion; classification: test fixture issue, fixed now. Broader source/native/
  lifecycle/hardware/GUI/merged/distribution run: 112 passed. Final focused run:
  26 passed. Touched Ruff F/E9 and `git diff --check` passed.
- The actual importer installed the official archive in the isolated build data
  directory and verified all 82 files. The real CDN honored an exact final-1024-
  byte resume request; returned bytes matched the verified archive.
- Full gate `evidence/CETA_OFFLINE_MANAGED_RUNTIME_20260927.json`: **609 run,
  608 passed, one environment skip**, zero failures/errors, 167.135 seconds.
  The temporary volume lacks a distinct Windows 8.3 alias. All 219 source files
  remained unchanged during verification.
- `evidence/CETA_OFFLINE_MANAGED_SERVICE_20260927.json`: two passed real owned
  service start/health/stop cycles using the imported runtime and managed child
  environment, expected version 0.34.3, 82 pinned files verified, zero active job
  members after each stop. No model load/download/inference or OS network isolation.
- Both reports bind source SHA-256
  `3c811e8c804aaf9dddb387046ad54d40412977ce3083a102e168be8bf5ac677f`.
  Native capture `evidence/CETA_OFFLINE_MANAGED_RUNTIME_UI_20260927.png` was visually
  inspected; new controls and descriptions are readable at 1440x1080. It uses
  synthetic hardware and temporary data. Source manifests/checksums are refreshed
  and checked after final record edits.

Remaining issues require follow-up within the active goal: managed model catalog
and acquisition, exact tokenizer/immutable runtime/model lifetime binding, complete
guided setup, two-second cancellation/whole-request deadlines, explicit abandoned-
stage discard/repair, real-weight and frozen/offline/hardware qualification, plus
all other original work packages. Pre-start file hashes are not protection against
subsequent same-account mutation. Optional ROCm/MLX distributions and actual device
support are unqualified. No new installer, signing, commit, push or publication.

## 2026-09-27 — Managed models and real governed local generation

Continued the full offline-product objective in the same CETA checkout, branch
`codex/ceta-desktop-release`, HEAD
`aadbeb1aff74118e6042cd5194268ebba6d18e28`. Preserved dirty/untracked work and all
earlier evidence. No other personal project's content was transferred. Official
third-party model assets were acquired for this CETA implementation and tested
only with synthetic prompts in an isolated build data directory.

Added `model_catalog.json`, `model_installation.py`, native `pages/model_setup.py`,
their deterministic tests, and reusable `scripts/verify_managed_model.py`.
The six Qwen3 candidates pin raw manifests, model/configuration/template/parameter/
license blobs, and runtime compatibility to Ollama 0.34.3. Exact digest downloads
support resume and preserve incomplete/corrupt/unknown files. Size, hash, ZIP
directory and path checks precede publication. Offline export/import preserve
license files and do not transfer conversations, authority or hardware readiness.

The Models page has explicit model download/import/export, pause, license and
use/test controls. Candidate suggestions use fresh hardware from the executing
computer; no development-machine hardware values are shipped as defaults. A
fitting balanced candidate is preferred, with larger candidates selectable.
Use/test checks installed file hashes and the owned service's reported digest
before selection and a governed short response probe. Worker cancellation stays
attached through the verification/probe handoff. Owned chat and probe connections
check job membership. Managed runtime startup disables automatic blob pruning.
The build includes the model catalog, and `model.export` is a registered action.

Validation and evidence:

- Focused acquisition/runtime: 33 passed; managed model/runtime/hardware/request
  checks: 78 passed; extended native setup/handoff/lifecycle checks: 81 passed.
  Touched Ruff F/E9 and `git diff --check` passed.
- Actual Qwen3 0.6B download: 522,653,767 bytes, five pinned files, manifest
  `7df6b6e09427a769808717c0a93cadc4ae99ed4eb8bf5ca557c90846becea435`.
- `CETA_OFFLINE_MANAGED_MODEL_REAL_20260927.json`: ten passed observations across
  owned health, governed probe/chat, resident unload, cancelled output, confirmed
  zero-worker stop, ended-job reconciliation, restart and successful probe.
  Cancellation remained uncertain until owned shutdown/reconciliation. Residency
  reported 4096 context tokens and zero VRAM use: actual CPU-path evidence only.
  The small model failed the exact `CETA_READY` instruction despite visible text;
  classification: quality limitation observed, W07 qualification still required.
- `CETA_OFFLINE_MANAGED_MODELS_20260927.json`: 629 run, 628 passed, one environment
  skip, no failures/errors, 164.438 seconds including overhead. The temporary
  volume lacks a distinct Windows short-path alias. This is the completed source
  gate, not a newly installed application test.
- `CETA_OFFLINE_MODEL_ROUNDTRIP_20260927.json`: actual export/import passed into a
  separate data directory with the downloader forbidden during import. ZIP size
  522,655,999 bytes, SHA-256
  `3a6983f4b1f044437324208368c67cd706577ab2ae9d2793e24535f2f2d5bb1e`.
- All three reports match the 225 current attributed source files and digest
  `3ef2bd1afc62afd822d330e247d4ac41d32294f206d31e41587777c13d6b99a0`.
  `CETA_OFFLINE_MANAGED_MODELS_UI_20260927.png` was visually inspected: readable
  native controls at 1440x1080 using synthetic hardware and temporary data.
  Delivery/dependency/implementation notes are updated. Source manifests and
  checksums are regenerated and checked after these final record edits.

The user's implementation-status question is answered by current source and
evidence: the managed local text path is implemented and exercised, while the
dependable offline product remains incomplete. Guided first-run/existing/skip
journeys, immutable asset lifetime, exact tokenization, whole-request deadlines,
failed-stage repair, capability measurements, actual GPU lanes, archive/search,
OS-isolated frozen/installer qualification and the other original work packages
remain follow-up work within the active goal. More hardware enables candidate
choices; it does not itself prove additional capabilities. No OS network-isolated
run, new installer, signing, commit, push or public release occurred here.

## 2026-09-28 — Guided setup and actual native offline-import/restart journey

Classified the preceding goal turn as progress: managed-model evidence, native
capture, delivery records and source-package checks were completed. Continued the
original full offline-product objective in the same CETA root/branch/HEAD,
preserving dirty/untracked work, ignored assets and historical evidence. No other
personal project's material crossed the boundary.

Added `src/ceta_desktop/pages/local_setup.py`, integrated it into Chat and Models
in `app.py`, added twelve guided journey tests, and added the reusable actual
native harness `scripts/verify_guided_setup.py`. A first-run entry offers managed
setup, an existing local service or continuing without AI. Models retains the
guide. Hardware/disk inspection is asynchronous and candidate selection uses the
executing computer. At most three estimated choices are shown with sizes,
destination, context, source and licenses. **Install and test** combines the
existing governed asset actions, re-verification, owned service health and probe.
Offline runtime/model ZIP import and a download-free installed recheck are explicit.

Preserved existing advanced controls. Setup blocks competing model controls and
keeps chat drafts while changing runtimes. Pause survives handoffs and late results;
owned workers used by setup are stopped, while existing external services are not
restarted or stopped by their discovery/test path. Choices survive restart, but
no live hardware/readiness result does. Changed settings/runtime state invalidate
the displayed test. Owned health now binds the worker's cancellation event before
execution to avoid losing a cancellation during startup.

Validation:

- Existing native setup/hardware/navigation: 35 passed. Initial new guided suite:
  11 run, one failure at its six-second repeated-recheck fixture wait. The same
  live journey completed in 7.015 seconds under diagnostic observation. Updated
  only the whole-fixture wait to 15 seconds, retaining its completion assertions;
  no production timeout was relaxed. Classification: fixture timing, fixed now.
- Added draft-preservation coverage. Combined guided/model/runtime/lifecycle/
  hardware/navigation suite: 63 passed. Touched Ruff F/E9 and diff whitespace
  checks passed. Full gate `evidence/CETA_OFFLINE_GUIDED_SETUP_20260928.json`:
  641 run, 640 passed, one environment skip, no failures/errors, 184.875 seconds
  including overhead. Skip: no distinct Windows short-path alias on the temporary
  volume. All 228 attributed source files stayed unchanged and match the actual
  native-journey source digest below.
- `evidence/CETA_OFFLINE_GUIDED_SETUP_REAL_20260928.json`: actual source MainWindow
  offline import of the pinned runtime and Qwen3 0.6B, real local probe, confirmed
  shutdown, reopened app with preference but no readiness, installed recheck and
  another real probe, then confirmed shutdown. Both stops reported zero active
  owned workers. Response times were 2.703 and 2.093 seconds; both reported zero
  VRAM. All 82 runtime files and five model files verified. Synthetic prompts only.
- The harness forbade the CETA runtime/model download transports and supplied only
  the file-dialog archive choices. It did not mock hardware, process ownership,
  service metadata or inference. This is transport-free setup on the observed
  CPU path, not OS network isolation or frozen/installed-application qualification.
- `evidence/CETA_OFFLINE_GUIDED_SETUP_UI_20260928.png` was visually inspected at
  1440x1080; the candidate, memory observation, sizes, location, actions and actual
  short-response result/limits are readable. The model's instruction following
  remained inconsistent, so no quality or GPU capability was promoted.
- Real journey source SHA-256:
  `b6a22f3a61b9de7c5072a5ffae27a736d742391e96f4ad016297e490690ddcf4`.
  Delivery and implementation records are updated; source manifests/checksums
  are refreshed and checked after the final evidence records.

Remaining work stays in the active goal: exact tokenization, immutable asset
lifetime, whole-request deadlines, failed-stage repair, measured configuration-
bound capabilities, hardware failure/qualified-candidate presentation refinements,
archive/search/responsiveness, actual GPU and OS-isolated frozen/installer lanes,
training dependency qualification and authorized final release. Historical hardware
and source evidence are not transferred to another installation as readiness.
No commit, push, new installer, signing, publisher-key use or publication occurred.

## 2026-09-28 — Exact managed request token counts

Classified the preceding status-answer turn as no progress: it refreshed evidence
but made no implementation change. Resumed the full offline-product goal in this
same CETA checkout/branch/HEAD. Preserved all earlier work and evidence; no other
personal project's material crossed the boundary.

Added `request_tokens.py`, owned-worker/process-image inspection, and optional
tokenizer scalar inspection for GGUF. Task preparation now uses exact rendered
counts on the pinned managed Ollama/Qwen3 path. It verifies assets, performs fresh
memory admission before render/load, holds the runtime lease, and binds the count
to the observed worker/model/context. Cancellation and malformed rendering cannot
silently become successful readiness. The receipt records template/message hashes,
the count and worker identity; the preview distinguishes counted from estimated
input. Changed worker/configuration/text rejects dispatch. Ollama completion
requests disable truncation/context shifting, and evaluated input must agree with
the prepared count. External/unsupported configurations retain their explicit
unverified estimate. No GPU or quality claim follows from an exact count.

Initial regression: 54 passed. New token/request/ownership suite: 64 passed.
Extended native setup/request suite: 91 passed. Ruff F/E9 passed. The first actual
diagnostic rejected Ollama's omitted zero `image_count`; the pinned API declares
that omission. Corrected the parser and preserved the failed diagnostic. The
second actual diagnostic passed ten local model/lifecycle steps and matched
113 prepared tokens to 113 evaluated tokens. Classification: API mismatch fixed.
The adversarial real run matched three additional cases, then hit the GGUF
inspection deadline. Diagnosis found authority polling starvation when journal
checks exceeded the polling interval: 0.840 seconds for the plain parser versus
5.051 seconds/46 checks with task authority, each check taking 0.084-0.133 seconds.
The interval now starts after check completion. No parser limit was relaxed;
immediate user cancellation and revocation checks remain. Added the regression
and passed 69 token/task/role/request tests. Classification: starvation fixed.
The failed real report is retained. The repaired run passed 15 observations,
including exact Unicode/control-text/history/long-prompt counts (192/126/126/1106),
oversized-input refusal before generation intent, and cancellation/restart.
Final review fixed stale metrics after preflight failure and cancellation-event
replacement before the client guard. Added tests; 44 focused tests passed. Full
source gate `CETA_OFFLINE_TOKENIZER_20260928.json` passed: **660 run, 659 passed,
one environment skip**, no failures/errors, 196.015 seconds including overhead.
The temporary volume lacks a distinct Windows short-path alias. All 230 source
files stayed unchanged, SHA-256
`a5f0f3e392189a424d01b0fb60f1d9d368d4f4d4cd709cc292fb9ba1aba27c22`.
`CETA_OFFLINE_TOKENIZER_QUALIFIED_20260928.json` passed all 15 actual-model checks
against the same final digest. Four boundary cases matched evaluated counts;
oversized input produced no generation intent, and both stops observed zero
owned workers. These are source/actual-model observations, not GPU quality,
OS-isolated offline, frozen-application or installer qualification.
Native counted-request preview `CETA_OFFLINE_TOKENIZER_PREVIEW_FONTS_20260928.png`
was visually inspected at 1440x1080 with a synthetic model/count fixture. The first
offscreen capture had missing glyphs; registering installed Windows fonts in the
capture process resolved it. Both images are retained; no application font change.
Manifest/checksum regeneration, both check modes and package verification passed
with 398 payload files, 399 checksum entries and 400 registered package files.

Still required: immutable asset lifetime; wider tokenizer/model qualification;
whole-request deadlines; failed-stage repair; measured capabilities; actual GPU,
OS-isolated frozen and installer qualification; all remaining original work
packages and authorized final release. No commit, push, installer, signing or
publication in this increment.

## 2026-09-28 — Protected managed runtime/model asset sessions

Answered the user's implementation-status question against the live checkout and
retained evidence: the offline product has substantial source implementation and
actual CPU inference evidence, but remains incomplete/unreleased. Hardware is
observed on each executing machine; the development host's observations are not
another installation's readiness. Continued the active full-product objective in
the same CETA root, `codex/ceta-desktop-release`, HEAD
`aadbeb1aff74118e6042cd5194268ebba6d18e28`. Preserved dirty/untracked/ignored work.
No other personal project's material crossed the boundary.

Completed the pending managed-session integration and added Windows protection
tests. `managed_assets.py` acquires read handles before hashing, denies write/delete
sharing, protects containing directory names, verifies canonical handle identities
and rejects links, unexpected tree changes and unreadable inspection. Files remain
held until owned workers report zero active processes. Shared model manifests/blobs
join the same session; cache reuse requires uninterrupted protection. Native startup,
model selection, guided setup and tokenization/generation now bind that session.
Cancelled/stale callbacks and failed verification release only unused protection;
query uncertainty retains running-worker protection. A hash operation observes
nonblocking close/cancellation before releasing its handles.

Initial focused run: 59 tests, ten errors caused by a mock reserving the real method
name `assert_runtime`. Explicit mock method fixed the fixture; 90 affected native,
tokenizer and owned-lifetime tests passed. Final containing-directory rename,
existing writable mapping and unreadable-directory tests passed with token tests:
38 passed. Ruff F/E9 passed. The first real diagnostic stopped on the harness
expecting a Windows sharing error from Python's CRT open, which retained only errno
13. Replaced that access probe with direct Win32 OPEN_EXISTING and no write call;
classification: harness issue fixed. Failed report preserved. The subsequent
`CETA_OFFLINE_ASSET_LIFETIME_REAL_FINAL_20260928.json` passed 19 observations,
including denial/release for 88 files, actual Qwen3 0.6B chat/token boundaries and
cancel/reconcile/restart with zero-worker stops. It precedes the final ancestor/
inspection fixes; final-source qualification is recorded below after completion.

Remaining W03 limits are explicit: parent-crash lock lifetime, additional loader/
device qualification and runtime-directory new-entry races are not an OS sandbox.
The wider goal still includes whole-request deadlines, failed-stage repair,
configuration-bound capabilities, hardware failure presentation, archive/search/
responsiveness, real GPU and OS-isolated frozen/installer lanes, dependency advisory
work and authorized final delivery. No commit/push, installer, signing, publisher
keys or public release were used for this increment.

Final source gate `CETA_OFFLINE_ASSET_LIFETIME_20260928.json`: 681 run, 680
passed, one environment skip, no failures/errors; 185.703 seconds including
overhead. The skip is the temporary volume's unavailable Windows short alias.
All 232 attributed source files stayed unchanged, SHA-256
`3570fd06617d8da7b19432fbcf784539bd474202be482d8e4b4e2e37b3098a17`.

`CETA_OFFLINE_ASSET_LIFETIME_QUALIFIED_20260928.json` passed 19 real-model
observations against that same unchanged source: 88 runtime/model files denied
write access with sharing error 32, all synthetic token/inference/lifecycle cases
passed, and both zero-worker stops released write access. Earlier diagnostic
evidence remains attributed to its recorded source. This is CPU source evidence,
not GPU, quality, OS-isolated or installed-product qualification.

`CETA_OFFLINE_ASSET_LIFETIME_GUIDED_20260928.json` passed the actual native
offline import, probe, close, reopen, installed recheck and second probe against
that same final source. Download transports were forbidden. Hardware, workers and
inference were real; only archive file-dialog choices were supplied. Both stops
reported zero workers; preferences survived without readiness. Probe durations
were 0.781 and 1.532 seconds with reported VRAM zero. The small model's response
format remained inconsistent: text liveness passed, instruction quality remains
unqualified W07 work. No model-quality claim was added.

Final source-package manifest generation/check, checksum generation/check and
package verification passed: 405 payload files, 406 checksum entries and 407
registered package files. This source increment does not complete the original
product objective.

## 2026-09-28 — Shared request deadlines and cancellable hardware inventory

Confirmed the preceding asset-lifetime increment made implementation progress and
continued the active full offline-product goal. The user's implementation-status
question was answered from the live source: substantial local source functionality
exists, but measured per-configuration capabilities and installed delivery remain
unfinished. Work stayed in this CETA repository, `codex/ceta-desktop-release`, HEAD
`aadbeb1aff74118e6042cd5194268ebba6d18e28`. Dirty, untracked and ignored work was
preserved. No other personal-project material was imported.

Added one process-bound monotonic request budget spanning native preparation,
preview review and generation. Context scans, Git inspection, exact token counting,
hardware inspection and HTTP connect/read/write observe it and cancellation.
Foreign/changed receipts cannot renew an admitted request's budget. Expired review
retains the composer; generation timeout retains partial output/retry material and
has its own native status without setting the user's Stop event. Provider monitor
shutdown prevents a late cancellation callback affecting a reused client. Existing
uncertain-backend and stop/reconcile rules remain enforced.

Hardware refresh passes the active cancellation event. Windows NVIDIA/PowerShell
queries and DXGI inspection use contained helpers with time/output limits. DXGI has
a source child and a frozen entry point; only source-child execution is qualified
so far. The inventory child's memory budget is not an inference-placement claim.
RAM-only admission skips GPU inventory. Guided refresh failure clears stale
hardware text/choices. No host-specific hardware defaults were added.

The affected regression suite passed 205 tests; final fault coverage passed 17.
Ruff F/E9 passed. First full gate `CETA_OFFLINE_REQUEST_DEADLINES_20260928.json`
ran 701 tests with one failure, zero errors and one environment skip: the old
socket test required the phrase `two minutes`, which is inaccurate when the shared
budget has less time remaining. Updated the assertion to check the deadline error
type, elapsed simulated read limit, remaining-time message and unset cancellation
event. Classification: test conflict fixed now. Focused transport/deadline rerun
passed 20 tests. The failed report remains unchanged. Final full gate
`CETA_OFFLINE_REQUEST_DEADLINES_FINAL_20260928.json` passed: 701 run, 700 passed,
one environment skip, no failures/errors, 188.531 seconds including overhead.
The skip is the temporary volume's unavailable distinct Windows short alias.
All 234 attributed source files remained unchanged, SHA-256
`bcb2c8fdf917b3d1f4ceaafe9294d9d2c01736badbb813be81e8a20f621321af`.
Touched-file Ruff F/E9 and `git diff --check` passed. Actual model/native setup
results are recorded below.

Known W04 limits remain classified as separate follow-up within the active goal:
blocking filesystem/SQLite calls, terminal audit writes and shutdown cleanup have
no demonstrated universal hard latency bound. Arbitrary blocking callbacks are not
forcibly interrupted. The real harness's new consumer-delay case is explicitly
synthetic delay after real model output, not evidence that the backend itself
stalled. Frozen-helper execution, measured capabilities, GPU/OS-isolated installed
qualification and the other original work packages remain outstanding. No commit,
push, installer, signing, publisher-key use or public release occurred.

Actual-model report `CETA_OFFLINE_REQUEST_DEADLINES_REAL_20260928.json` passed
26 observations against the same unchanged 234-file source. The controlled
consumer-delay case returned `timed_out` at 30.828 seconds for a 30-second shared
budget, retaining partial text `Here` and leaving the caller's cancellation event
unset. Backend state stayed uncertain until stop/reconcile; restart answered again.
All four tokenizer boundary cases matched evaluated counts; oversized input was
refused. Three shutdowns observed zero active workers and released all 88 protected
files after write access had been denied while active. Runtime-reported VRAM was
zero. Instruction following was still inconsistent, so W07 quality remains
unqualified. A read-only process diagnostic initially hit the tool sandbox's WMI
access denial; the scoped elevated read succeeded. Classification: environment
restriction resolved for diagnosis, no application permission changes.

Native guided report `CETA_OFFLINE_REQUEST_DEADLINES_GUIDED_20260928.json` passed
offline import/test, close, reopen, installed recheck/test and close against that
same unchanged source. Download transports were forbidden; only explicit archive
dialog choices were supplied. Both stops observed zero workers. The model choice
survived without readiness. Actual probes took 1.281 and 1.016 seconds, reporting
zero VRAM use. This remains source-level CPU text liveness, with inconsistent
instruction following; no frozen-helper, installed-app, OS-isolation or quality
claim was promoted. The next product-facing increment is W07 configuration-bound
capability observations and native results presentation. W03 crash/loader protection,
W04 hard-latency qualification and every original remaining package stay in scope.

Final source manifest/checksum generation, both check modes and package verification
passed: 411 payload files, 412 checksum entries and 413 registered package files.
Historical failed reports remain intact. This increment made implementation progress
but does not complete the offline-product objective. No commit/push, installer,
signing, publication or other project transfer occurred.

## 2026-09-28 — Explicit measured text capabilities

Classified the preceding deadline increment as progress: source, actual-model and
native offline setup evidence passed. Continued the same full-product goal in this
CETA checkout, branch `codex/ceta-desktop-release`, HEAD
`aadbeb1aff74118e6042cd5194268ebba6d18e28`, preserving all prior work. No personal-
project content or authority was imported.

Added a capability measurement module and native Measure/Stop/Previous measurements
controls. The disclosed action runs seven synthetic requests through ordinary
governed generation: cold, two strict instruction fixtures, selected-file attachment,
and three warm samples. It explicitly unloads only the selected digest for the cold
sample, refuses ambiguous residency and retains the synthetic file in this profile.
Fixture outcomes, wall-clock first-visible/total times and runtime-reported token/
duration fields are separate observations. The pinned Ollama 0.34.3 API types were
checked for the metrics contract. Unknown telemetry never becomes fabricated speed.
Quality failures do not become successful capability claims or abort unrelated checks.

Observations bind application code/build, fixture revision, process session, hardware,
runtime archive, model/profile, managed asset session, worker and generation settings.
The canonical application journal retains intent/results alongside normal request
evidence. Native settings/hardware/worker changes invalidate the displayed result.
Restart and historical records never restore live readiness. Reviewed code effects,
larger contexts, GPU placement, vision, voice and autonomy remain unqualified.

Initial capability run: 12 tests, one fixture newline/hash mismatch on Windows.
Changed synthetic creation to exclusive UTF-8 with LF. Affected native suite: 68 run,
67 passed, one returned-versus-persisted tuple/list mismatch. Normalized the report
to JSON-compatible data before persistence and return. Both classified fixed now.
Final focused suite: 15 passed, including actual TaskRuntime/attachment binding with
a synthetic provider, negative quality/telemetry/residency cases, session/configuration
invalidation and native cancellation/history. Touched-file Ruff F/E9 passed. The
actual managed-model measurement run is pending; no capability is claimed from
synthetic fixtures alone. The native guided harness now also supports an explicit
measurement button journey and verifies historical-only results after restart.

W07 measured candidate ranking and wider coding/file fixtures, W08 responsiveness/
archive/search and all original remaining packages stay in the active objective.
No commit/push, frozen build, installer, signing, publisher-key use or release.

The retained actual-model diagnostic `CETA_OFFLINE_CAPABILITIES_REAL_20260928.json`
passed 15 execution/lifecycle observations against source
`83863c48e02835bd81ec390ebdbffe14b8695223690508958a9121d8bd4047fa`.
The seven-request suite completed in 182.484 seconds, with text liveness passing,
both exact instruction checks and strict selected-file JSON format failing. Warm
first-text times were 23.453/23.265/24.047 seconds, versus about 41-45 reported decode
tokens/second; the fresh file-fixture project reached first text in 3.125 seconds.
Classification: application/profile latency requires W08 profiling and repair;
general model quality remains unqualified. No GPU capability was inferred.

Diagnostic review caught a warm unrelated answer counted as matched by the liveness
predicate. Tightened warm matching to the complete 1-60 sequence; speed labels now
require three matching, sufficient samples. Also bound the synthetic file to its
created hash before attachment admission, refusing/preserving changed bytes. These
two regressions are fixed; 16 focused tests pass. The diagnostic's warm classification
is superseded, not rewritten. Final source/native results are recorded after execution.

Source gate `CETA_OFFLINE_CAPABILITIES_20260928.json` passed 717 tests (716 passed,
one environment skip) against unchanged 237-file source
`5fa39f8a9c40bfee9a9d08fc8eeb5ce56b31f6b9c3d7f25a9f9450061e843423`.
`CETA_OFFLINE_CAPABILITIES_GUIDED_20260928.json` passed native offline import,
explicit measurement, close/reopen/recheck, historical-only measurement display and
close against that source. Both stops observed zero workers. The suite took 61.672
seconds; text passed, strict instruction/file-format checks failed, and unmatched
warm output correctly kept speed unmeasured. The 1440x1080 native screenshot was
visually inspected: current hardware, workload disclosure, controls, failed checks,
observed answers and scrollable results were readable.

Final review added deadline checks after metadata and before suite acceptance;
late final inspection cannot promote a completed-but-expired suite. The UI now
states a 21-minute request budget with inspection/stopping overhead. The new
negative test passed with the full focused suite: 17 passed. Final gate/native
reruns are pending; the earlier same-source pair remains historical evidence.

Read-only inspection of the synthetic old-profile warm_1 timeline located
`task.context` at 5.450 seconds after task creation, `provider.prepared` at 14.679,
and `provider.intent` at 18.398. First visible text was 23.453 seconds after the
measurement request began. `Journal._verify_project` currently scans/hashes the
entire project stream on each call, including nested transaction paths. This is a
specific W08 profiling lead, not a proven sole cause or permission to skip checks.
Next repair must preserve tamper, truncation, concurrency, authority and replay
tests while measuring prepare/dispatch wall time on both fresh and accumulated
profiles. Existing data and diagnostic reports must remain intact.

Final source/native verification completed against unchanged 237-file source
`1dd55dc6b89565a4c3cf3f0346601865667f0f120755626b81a5a394d0a5ad21`.
`CETA_OFFLINE_CAPABILITIES_FINAL_20260928.json`: 718 run, 717 passed, one environment
skip, zero failures/errors, 212.282 seconds including overhead. The skip is the
temporary volume's missing distinct Windows short alias.
`CETA_OFFLINE_CAPABILITIES_GUIDED_FINAL_20260928.json`: actual native offline import,
explicit measurement, close/reopen/recheck, historical-only capability display and
final close passed. Both closes observed zero workers. The seven-request suite
completed in 63.844 seconds; text liveness passed, both strict instruction checks
and selected-file JSON formatting failed. An unmatched warm answer correctly kept
speed unmeasured; warm first-visible times were 5.031/6.438/6.109 seconds with about
41-42 reported decode tokens/second. The final 1440x1080 native screenshot was
visually inspected and is readable. Classification: capability measurement delivery
verified for this source path; general model quality and profile latency remain
follow-up work under W07/W08. This run does not qualify GPU execution, OS network
isolation, frozen bytes or an installer. Full offline-product objective remains active.

Source-package manifest/checksum generation, both check modes and verification
passed: 421 payload files, 422 checksum entries and 423 registered package files.
Preserved all earlier diagnostic reports and prior dirty work. No commit/push,
installer build, signing, public release or personal-project transfer occurred.

## 2026-09-28 — Repeated journal verification latency

Classified the preceding goal turn as progress: final capability source/native
verification, package records and current limitations were completed. Continued
the full offline-product objective in this same CETA checkout and branch; prior
dirty work and historical evidence remain preserved. No project transfer.

Read-only cProfile on the existing synthetic managed-model profile confirmed that
three task/events/head read sequences rehashed 1,839 application events 22,068 times;
canonical validation/serialization dominated. Added a bounded exact-row hash cache
to Journal. Every persisted field and type must match; all reads still query the
database and check stream structure, identity, tasks, checkpoints and observed
history. No decoded mutable payload is shared. Limits: 4,096 rows and conservative
8 MiB row accounting, with ordinary full verification after eviction or for large
rows. Closing the journal releases cached rows.

Seven deterministic regressions cover changed fields, external tampering/append,
projection changes, rollback, return-value isolation and cache limits. Initial
28-test run had one Windows test cleanup error because a SQLite context manager
does not close its connection. Fixed the test connection's lifetime. Expanded
journal/task/preparation/authority/replay suite: 85 passed in 21.722 seconds.
Touched Ruff F/E9 and whitespace checks passed.

The new read-only `profile_journal_reads.py` harness compares both paths on one
SQLite snapshot and records source attribution, counts and timings without event
payloads. `CETA_OFFLINE_JOURNAL_PROFILE_20260928.json`: uncached 1.133225 seconds /
22,068 hashes versus bounded-cache 0.478649 seconds / 1,839 hashes, including cache
warmup. About 58% less time in this specific read workload; 5,212,313 accounted row
bytes retained. Full source and actual model follow-up are pending. This does not
close W08 archive/search/UI responsiveness or qualify general answer quality.

Full desktop/governed-runtime gate `CETA_OFFLINE_JOURNAL_CACHE_20260928.json`
passed 725 run: 724 passed, one environment skip, zero failures/errors, 184.219
seconds including overhead. Skip: temporary volume lacks a distinct Windows short
alias. The 238 attributed source files stayed unchanged at SHA-256
`943fc7244b1e70d17dd9aeaa576e19eacdfac0353f0956e6a4c29b4d7cd33d36`.

`CETA_OFFLINE_JOURNAL_CACHE_REAL_20260928.json` passed 11 actual-model/lifecycle
observations against that source; both stops observed zero workers. Seven capability
requests took 122.937 seconds. Warm first text was 15.500/15.157/15.641 seconds versus
the prior 23-24 seconds, while the accumulated history had grown. This is an
observational comparison, not a controlled timing ratio. Model quality checks still
failed and speed remained unmeasured. Classification: latency improved, still too slow.

Follow-up inspection found repeated whole-stream reads within `_access`. Added one
verified task/history snapshot and reused it within each access decision, access-status
inspection and timeline read. Signature/principal/expiry/revocation/operation checks
remain; subsequent decisions read current history again. No authority result is cached.
Three further regressions cover independent returned state, one verification per
access decision, denied operations and revocation from a separate runtime. Final
source and actual model verification are pending for this follow-up change.
The expanded journal/task/preparation/authority/replay/roles/recovery run passed
107 tests in 29.819 seconds. Touched-file Ruff F/E9 passed again.

Final source gate `CETA_OFFLINE_JOURNAL_SNAPSHOT_FINAL_20260928.json`: 728 run,
727 passed, one environment skip, zero failures/errors, 173.140 seconds including
overhead. The Windows short-alias skip remains. All 238 attributed source files
stayed unchanged at SHA-256
`a07394382bbea6913f0e3e3ba665b0b373ca47fc2f8f3376d0d12a034a5290e2`.

Same-source `CETA_OFFLINE_JOURNAL_SNAPSHOT_REAL_20260928.json` passed 11 actual-model
and lifecycle observations. Both stops observed zero workers. Seven capability
requests took 90.922 seconds; warm first-visible times were 9.532/9.109/9.156 seconds,
versus the cache-only 15-16 and original 23-24 seconds. History grew between these
runs; this is observational evidence, not a controlled speedup ratio. Strict
instruction/file-format failures and unmeasured warm quality/speed remain visible.

The final warm_1 timeline places task.context at 3.204 seconds, provider.prepared
at 6.001, provider.intent at 8.225. The application stream now contains 2,415 events.
Classification: meaningful latency repair, accumulated-history responsiveness still
requires follow-up. Profile context compilation, preparation and final admission
separately before further changes; preserve tamper/revocation/replay checks. Bounded
cache storage does not remove full row scans or uncached work in larger histories.

`CETA_OFFLINE_JOURNAL_SNAPSHOT_SMALL_PROFILE_20260928.json` passed 11 real-model/
lifecycle observations on the same final source using the smaller existing synthetic
setup profile. Seven requests took 46.281 seconds; warm first text was
3.422/3.766/3.546 seconds. Both stops observed zero workers. Strict quality failures
remained and the speed capability stayed unmeasured. Prioritize history-dependent
context/preparation/admission profiling and keep quality repair independently tested.
All original work packages remain in scope. No installer, GPU qualification, OS
network-isolated run, signing, publication or project transfer occurred.

Final source-package manifest/checksum generation, both check modes and verification
passed: 428 payload files, 429 checksum entries and 430 registered package files.
Touched Ruff F/E9 and whitespace checks passed. No commit or push occurred; all
earlier diagnostic evidence and unrelated dirty work remain preserved. Classified
this goal turn as progress; full offline-product completion is still unproven.

## 2026-09-28 — Ordinary-chat prompt repair

Classified the preceding goal turn as progress: journal latency repairs and source/
real-model evidence were completed. Continued the same full-product goal, root,
branch and HEAD, preserving existing dirty work and prior reports. No project transfer.

Read the exact synthetic prepared request: application chat always received coding-
explanation/source-citation instructions and internal task metadata. The 0.6B model
answered an exact-token prompt by claiming a file-related instruction had been
executed. Changed the ordinary-chat system prompt to answer the latest question
directly and follow its requested format, including JSON without unsolicited fences.
It retains uncertainty and truthful action claims. Project instructions/context and
selected-source data treatment remain; application labels/ids stay in governed
receipts instead of ordinary-chat model instructions. No execution gate or authority
check changed. Existing capability prompts and pass criteria remain unchanged.

Two new deterministic allocation regressions cover ordinary-chat metadata isolation
and retained project/role instructions. Allocation/tokenizer/roles/capability suite:
56 passed in 16.696 seconds. Touched Ruff F/E9 and whitespace checks passed. Added
five independent ordinary-conversation cases to the real-model harness; quality
outcomes are separate from transport/lifecycle completion. Actual-model run pending.

`CETA_OFFLINE_CHAT_PROMPT_REAL_20260928.json` completed 16 execution/lifecycle
observations against unchanged source
`f7b8924e47e5be70c605d3bbef6cab99092f197ab01fae3ad691dff4a62eb2a4`.
The 0.6B model answered ordinary arithmetic coherently, passed recall/rewrite and
all three counting samples, but strict token/JSON/file formatting remained failures.
Number-only arithmetic and Unicode-copy formatting also failed. Unrelated JSON
answers coincided with JSON-specific default wording; removed that wording while
retaining general response-format guidance. Model quality is still unqualified.

Current hardware inspection selected the existing balanced Qwen3 4B Instruct catalog
candidate for CPU admission. Started pinned model.download acquisition into the
existing synthetic setup profile for actual qualification. No user profile choice,
model catalog default, hardcoded hardware or other project content changed. Integrity,
inference and quality remain separate gates.
