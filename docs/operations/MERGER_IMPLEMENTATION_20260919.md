# CETA and Model 001 merger implementation

Date: 2026-09-19. Status: IMPLEMENTED; unsigned local release candidate validated. Public release remains later.

The user instructed: "implement the plan pleaser and thank yuu" after approving the completed CETA + Project-AI Model 001 merger plan. This lifts CETA's read-only restriction for implementation of that plan. Later public deployment remains a separate release step.

Authorized source: T:\00-Active\Project-AI Model 001, selected governance, context, evidence, reasoning components and their relevant tests. Authorized destination: the existing CETA application at T:\00-Active\CETA-desktop-delivery-20260906. No other project material or private release keys are authorized for import. Model 001 source and historical records remain preserved in place.

Implementation uses the existing CETA delivery working tree at HEAD 7ebabf903c109d35c6cb7065ee68dd4f7d151b80, including its existing local changes. Source hashes and the initial dirty state were recorded before the first implementation edit in the current task output CETA_MERGER_BASELINE_20260919.json. No reset, clean, source-tree merge, deletion, rename, branch switch or remote mutation is authorized by this record.

The plan is CETA_MODEL001_MERGER_PLAN_2026-09-19.md in the current task output directory. The first implementation work connects project/task identity, a shared history and authority path, current context, provider calls and the desktop workflow. Subsequent editing, execution, migration and release checks remain part of the plan, with actual evidence recorded as they complete. A source feature or test result is not installer or public deployment evidence.

Transfer inventory, implementation details, validation results and remaining issues will be appended here as work progresses.
## Implemented application behavior

- Desktop version **0.4.0**, using the existing CETA product and checkout. The retained reference library version stays 0.3.0 for provenance.
- `runtime/tasks.py` connects actual native project inspection/search/context, local model generation, optional reviewer/specialist strategies, reviewed edits/manual saves, new files, bounded trusted-local commands, and application maintenance. Model readiness probes also use the same provider and task path.
- `runtime/journal.py` supplies one ordered, hash-chained authoritative stream per project in desktop SQLite schema 2. CETA authority, transition, identity and evidence owners use that shared transaction boundary through `journal_owners.py`. Bound conversations/workloads/settings are recorded projections, not separate live histories.
- Nine selected Model 001 source modules are integrated under `ceta_model001`; six generated integration surfaces are separately identified in `MODEL001_TRANSFER_20260919.json`. All nine original hashes and nine transferred/adapted destination hashes were reverified. No source ledger, active seed permit issuer, training code, model weights or historical Model 001 evidence was imported.
- Task grants use CETA signed assertions with project/task binding, expiry and revocation. Operational permits bind the exact registered adapter, arguments and context and are consumed before effects. Locally generated runtime keys are current-user DPAPI protected on Windows and separate from publisher signing keys.
- File edits preserve existing UTF-8/BOM/newline and Windows replacement/ACL behavior, reject stale content and aliases, and independently read back the reviewed bytes. A consumed proposal is never blindly replayed.
- Commands preserve executable/arguments/cwd/timeout identity, actual output and exit code; Windows job ownership supports owned-process cleanup. This is explicitly trusted local execution, with no filesystem/network sandbox claim. Process exit does not independently certify arbitrary semantic effects.
- Recovery derives unfinished provider/effect intents from history. Interrupted work is retained and uncertain effects require reconciliation. Asynchronous application callbacks record their observed lifecycle without claiming independent effect verification.
- Schema-1 migration creates an integrity-checked backup and preserves unassigned legacy data. Unsupported future schemas fail explicitly. Bound transcript archive semantics are visible in the UI. Historical CETA JSONL import requires explicit source, kind, SHA-256 and project provenance and never activates old permits.
- Installed distributions include the canonical CETA operation-contract resource. The release builder and desktop CI run one merged desktop/core gate. The packaged self-test and network-disabled Sandbox fixture cover the native workflow, migration, restart and unknown-data preservation without touching user data.

## Validation recorded before installer lifecycle

- Initial unchanged baseline: **416 tests**, successful with one Windows short-alias case skipped.
- Full `scripts/verify_all.py --hostile-report <new external path>`: **PASS**, all 18 stages. **564 tests** ran in 168.219 seconds, with one platform-specific skip. The hostile gate passed 11 checks over 1,380 curriculum cases. Its report was written outside the repository; historical epoch/heldout reports were verified and preserved.
- Final isolated desktop build gate: **475 tests** ran in 127.451 seconds, successful with one platform-specific skip. The build environment excludes Torch/Transformers/PEFT; `pip check` passed and its unsuppressed `pip_audit --local` reported no known vulnerabilities.
- Repository-wide `ruff check --select F,E9 src scripts tests examples` passed. Git whitespace validation passed; Git only reported existing CRLF-to-LF normalization notices.
- Actual extracted wheel test: the merged imports and operation-contract resource worked with `python -I`, no source checkout lookup, an actual governed file edit received `VERIFIED`, and reopening restored the same task/history.
- Native source CLI self-test passed with a new synthetic data directory: project open/search, diff review/apply, independent file observation, real command output, retained transcript, reopened history and unrelated file preservation.
- A real installed `qwen3:0.6b-q4_K_M` request through task context, the shared local provider and reviewer role completed and correctly described the synthetic `answer = 1 + 1` file without claiming execution. The journal verified and the role output remained an unverified proposal. No model was downloaded. The initial attempt was refused for insufficient measured free memory; after the full test process released memory, the unchanged guard admitted the successful attempt.

Evidence is in the current task output directory:
`C:/Users/Quencher/.codex/visualizations/2026/09/19/01a0bb3e-860d-75f1-974b-12e6e59151e2`.
Primary records are `ceta-merger-full-verification.log`, `ceta-merger-hostile-gate-final.json`, `ceta-merger-installer-build.log`, `CETA_MERGED_WHEEL_PROOF_20260919_bab68fb3/verification.json`, and `CETA_LIVE_MODEL_PROBE_85efbafa/result.json`. Failed initial checks and their outputs remain retained alongside the passing follow-ups.

## Issues found and disposition

| Issue | Disposition |
| --- | --- |
| Strict JSON journal rejected a verification StrEnum after the effect | Fixed: serialize the explicit enum value; retained durable uncertainty and added actual runtime/GUI/package verification. |
| New-file proposals, stale instruction scope and Windows inventory behavior | Fixed with exact-path/new-file/context and real filesystem regressions. |
| Concurrent action admission, expired/revoked authority and interrupted intents | Fixed and covered by runtime and journal regressions. |
| Corrupt bound views, nested transaction failures, unknown FK/trigger/column effects during rebuild | Fixed with checked canonical projections and refusal before unsafe rebuild mutation. |
| UI background-worker tests starved Python worker execution; a concurrency watchdog was too short under host load | Fixed bounded test event loops/watchdog only; assertions retained. |
| Export overwrite refusal lost the existing FileExistsError interface | Fixed preflight refusal while retaining exclusive create for race safety. |
| Readiness inference bypassed the shared provider; stale UI copy omitted automatic task context | Fixed actual call site and context disclosure. |
| Raw selected-root aliases could disappear during normalization; Git inspection output lacked a byte bound | Fixed original-path validation and bounded Git capture with explicit incomplete-state refusal. |
| Live model initially lacked sufficient free memory | Environment condition resolved after verification released memory; guard unchanged and successful live attempt recorded. |
| Duplicate `_workloads_page` methods present in HEAD | Not blocking this task; preserved as unrelated existing code. |
| Recorded Accelerate audit issue in the training dependency closure | Separate reference/training dependency follow-up; desktop closure excludes it and passed its own unsuppressed audit. This work does not claim the training audit issue resolved. |
| Historical first-attempt public TLS trust initialization limitation | Later network-enabled release validation; offline Sandbox does not certify public download behavior. |

No release was published, no website was deployed, no publisher private keys were accessed, and no existing installation or user database was used as a test fixture. Final installer/lifecycle evidence follows below when observed.

## Final local release-candidate result

**Implemented and validated locally as CETA 0.4.0. Public release remains a later step.**

The unsigned installer is `C:\Users\Quencher\.codex\visualizations\2026\09\19\01a0bb3e-860d-75f1-974b-12e6e59151e2\CETA_0.4.0_RELEASE_CANDIDATE_20260919\CETA-0.4.0-setup.exe` (44,090,880 bytes), SHA-256
`ddea9a61ae6951136493bf22db81401fe6b98c0ba2187a668960e40a77c5eef2`.
Its observed Windows product version is 0.4.0 and Authenticode status is NotSigned.
The matching dependency-source companion is `C:\Users\Quencher\.codex\visualizations\2026\09\19\01a0bb3e-860d-75f1-974b-12e6e59151e2\CETA_0.4.0_RELEASE_CANDIDATE_20260919\CETA-0.4.0-dependency-sources.zip`,
SHA-256 `063ed318ffdc8bf7e843cc47094ac721aab70218f36623f25406326bb0024778`.

The actual frozen executable passed against a fresh synthetic schema-1 database.
The **network-disabled Windows Sandbox lifecycle passed** using the verified prior
CETA 0.3.3 installer: old-version startup, upgrade to 0.4.0, schema-1-to-2 migration,
backup hash/schema/integrity, exact legacy and unknown rows, merged native workflow,
restart checkpoints, timeout and completed-parent update handoffs, repeated update,
and uninstall with application data and unrecognized files preserved. Three fresh
packaged self-test reports verified zero, one and two prior successful launches.
Command semantic effects remained INDETERMINATE; actual exit/output were retained.
The completed test Sandbox session was closed; exported reports/screenshots remain
at `C:\Users\Quencher\.codex\visualizations\2026\09\19\01a0bb3e-860d-75f1-974b-12e6e59151e2\CETA_MERGER_SANDBOX_20260919\results`. The host installation and user databases were not used or changed.

The machine-readable record is [CETA_MODEL001_MERGER_20260919.json](../../evidence/CETA_MODEL001_MERGER_20260919.json).
There are no remaining implementation or local lifecycle blockers from these checks.
The candidate is unsigned and unpublished. Publisher signatures, online update
verification and deployment to Thirstysystems.com require the later release step;
none is implied by the passing local tests.
