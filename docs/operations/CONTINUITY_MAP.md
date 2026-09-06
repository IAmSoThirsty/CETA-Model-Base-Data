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
