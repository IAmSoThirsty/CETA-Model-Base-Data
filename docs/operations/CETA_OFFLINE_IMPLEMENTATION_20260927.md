# Dependable offline CETA: implementation record

Date: September 27, 2026. Status: **in progress; the full product goal remains active**.

The user authorized implementing the dependable offline product described in
[the September 25 plan](CETA_OFFLINE_PRODUCT_PLAN_20260925.md). This record tracks
actual changes separately from that historical plan. Source remains the existing
`T:\00-Active\CETA-desktop-delivery-20260906` repository, branch
`codex/ceta-desktop-release`, baseline HEAD
`aadbeb1aff74118e6042cd5194268ebba6d18e28`. The pre-existing plan, continuity entry,
package manifest and checksums were preserved. No additional project content,
models, credentials, user conversations or evidence were imported.

## First increment: task renewal and preserved recovery (W02)

- Task authority can be inspected without renewal. Expired authority requires
  **Resume task**; revoked authority requires **Reauthorize task**. The UI rejects
  an action if authority changed after its button was displayed. The same
  project, task, objective, conversation and draft are retained. New grant events
  retain the old assertions and record the explicit user action.
- Context preparation is bound to the grant that preceded it. Renewal or
  reauthorization cannot revive an old reviewed edit or command. Generation
  rechecks context under the admission transaction. Operational permits are not
  renewed by the task-grant APIs.
- Expired chat submission is rejected before clearing the composer or creating
  a conversation/message. Recovery controls are available in Chat and Projects.
- Interrupted task IDs are presented at startup. Projects lists task states and
  offers **Inspect recovery** with the original action IDs. Uncertain effects
  block further edits and commands throughout the same project, including a
  different task; later successful chat cannot hide an unresolved effect.
- Reconciliation records either a user acknowledgment (which clears nothing)
  or a fresh observation of an edit's current file hash. An original/proposed
  revision can permit a newly reviewed operation; a different revision remains
  unresolved. Observing the current revision does not certify the original
  execution, and the original action cannot be replayed. Arbitrary command
  effects are not cleared by a generic reset.
- Startup reads and checks the database and identity before migrations, normal
  Store writes or key creation. Missing identity beside task history, malformed
  or inaccessible identity, mismatched signing identity, corrupt database and
  unsupported schema enter preserved recovery. Preference-only installation
  data can initialize independent local authority.
- The recovery window opens available conversation text read-only and can export
  it as explicitly unverified, non-authoritative material to a new file outside
  the original data folder. It never overwrites an existing export. Recovery
  advises retaining SQLite companion files and inspecting backups separately.
  Windows DPAPI identity portability across accounts/computers is not promised.
- The desktop verification report now records the exact selected test IDs,
  skip reasons, failures, source hashes before/after testing, Git state, lockfile
  and interpreter identity. A source change during testing prevents a passing
  report. Recovery tests are explicitly included in the release gate.

Primary changed surfaces: `src/runtime/tasks.py`, `runtime_keys.py`, `journal.py`;
`src/ceta_desktop/app.py`, `pages/tasks.py`, new `pages/recovery.py`;
new `tests/test_runtime_recovery.py`, `tests/test_desktop_recovery.py`;
`tests/test_merged_distribution.py`; `scripts/verify_desktop_runtime.py`;
`docs/DESKTOP_DELIVERY.md` and this record/continuity/source manifests.

## First-increment validation and repaired failures

Use the existing repository Python environment and set
`PYTHONPATH` to this repository's `src` and `tests` directories. The sandbox
blocked the uv Python launcher; approved execution of that same environment
resolved it. The initial direct unittest command also lacked the source import
path; configuring it resolved `ModuleNotFoundError: runtime`. These were
environment/command issues, not evidence of a working product.

- Baseline, before runtime changes: `python -B -X utf8 -m unittest
  test_task_runtime test_project_journal test_desktop_merged_tasks -q`:
  **71 tests passed**.
- New recovery regressions first reproduced missing APIs, silent replacement of
  missing keys and acceptance of a different identity. They also exposed test
  fixture cleanup issues; temporary SQLite handles and double window closure
  were repaired in the fixtures.
- `python -B -X utf8 -m unittest test_runtime_recovery
  test_desktop_recovery -q`: **20 tests passed** after those repairs.
- `python -B -m ruff check` on the changed runtime/UI/tests/verifier with
  `--select F,E9`: **passed** at that increment.
- Existing release-runner tests: **12 passed** before the additional source-change
  and exact-skip report regression was added.
- Initial full desktop/runtime report: `evidence/CETA_OFFLINE_RECOVERY_20260927.json`:
  **496 tests run, 495 passed, one environment skip**.
- Final focused recovery/native/verifier check: **34 passed**, including next-day
  native window restart. Final touched-file Ruff F/E9: **passed**.
- Final full report: `evidence/CETA_OFFLINE_RECOVERY_FINAL_20260927.json`:
  **497 tests run, 496 passed, one environment skip**, zero failures/errors.
  The skip is `test_short_directory_alias_resolves_before_locked_handoff`:
  the temporary volume does not provide a distinct Windows short alias.
  Source hashes were identical before/after the suite:
  `9d52586cf9767b971f245986a6272f480ae84928fad24dd4286514871483875e`.
- Native recovery controls were rendered and visually inspected using a temporary
  synthetic task and an advanced clock. The first offscreen image had unreadable
  glyphs: Qt reported zero discovered font families. Loading the existing Windows
  Segoe UI font explicitly into the test process corrected that environment issue.
  The accepted capture is `evidence/CETA_OFFLINE_RECOVERY_UI_FONTS_20260927.png`;
  the initial capture is retained as diagnostic evidence. No font or host setting
  was changed and no font was copied into CETA.
- Source-package manifest/checksum regeneration, both builders' `--check` modes
  and `scripts/verify_package.py`: **passed**, 338 registered payload files.
  These checks include the new source, documents, reports and diagnostic/accepted
  captures; they do not validate installer contents or model execution.

Tests use isolated temporary databases/files and synthetic model/process cases.
No ordinary app data, installed runtime, model weights or host hardware settings
were modified. This is source/native-test evidence, not an installed offline
model run, installer qualification, public release or signing result.

## Second increment: prepared requests and file snapshots (W01)

Implemented in source:

- Request preparation runs in a background worker before consuming the draft or
  appending a user turn. Changed drafts, stopped preparation, missing authority,
  stale file snapshots, oversized mandatory input and preparation failures retain
  the composer. A single storage transaction admits the conversation, user turn,
  assistant attempt and retry material; admission failure rolls them back.
- Attachments retain workspace/path identity, disk revision and the captured
  editor text with its own hash. Unsaved text can be used without writing the
  file. Editing an attached document marks its snapshot stale. Applicable nested
  instructions are compiled from the actual attachment paths; file text enters
  the final user message as untrusted data, not as system instructions.
- The request contains mandatory instructions, project/task context, selected
  role, attachments, a chronological suffix of paired conversation turns and the
  current user turn last. The allocator accounts for input, reserved output and a
  template allowance together. Mandatory input is never silently removed. Omitted
  file content requires explicit review before sending; omitted older history is
  disclosed without deleting the stored transcript.
- The advanced path currently uses an explicitly **unverified estimate**, based
  on UTF-8 bytes plus per-message and template allowances. It is not exact token
  counting or a proven tokenizer bound. The selected profile is currently at most
  4096 context tokens; ordinary chat reserves 1024 output tokens. W01 must integrate
  with W03 tokenizer/backend qualification before automatic setup can claim a
  guaranteed fit for a specific model and template.
- Prepared requests bind the captured source/context, grant, model configuration,
  role, actual transport payload and hashes to an expiring, single-attempt request
  record. The native preview exposes the exact outgoing payload. Dispatch checks
  source, authority and observed model configuration again after preflight. These
  checks detect changed runtime-reported metadata; mutable model tags still do not
  establish immutable execution identity.
- Failed attempts retain retry material. Restoring and retrying an unchanged
  request uses the original user turn with a new assistant attempt and a fresh
  prepared request. Source changes require fresh preparation. Archive/deletion
  clears associated attachment drafts and retry material through existing storage
  paths.
- Readiness probes now send the actual prepared request that their receipt names.
  Empty/whitespace completions and malformed generic streaming responses fail
  visibly. An already-set cancellation flag is no longer cleared during provider
  admission. Completion forces a fresh authority check, so short responses cannot
  evade a revocation/expiry merely by finishing inside the 100 ms polling interval.

Primary additional surfaces: new `src/runtime/generation_plan.py`,
`src/runtime/tasks.py`, `model_provider.py`, `journal.py`;
`src/ceta_desktop/app.py`, `models.py`, `storage.py`;
new `tests/test_generation_plan.py`, `tests/test_desktop_requests.py` and existing
runtime, roles, native chat, hardware and merger tests; the desktop verifier's
explicit test selection. Existing public storage message shape is preserved;
sequence identifiers are opt-in for retry handling.

Validation and failures:

- **23 focused request tests passed**, covering nested instructions, unsaved
  snapshots, stale drafts, preparation cancellation, omission review, the native
  preview event-loop race, transactional rollback, exact emitted payload binding,
  model/source changes at dispatch and retry without duplicate user turns.
- An earlier integrated **64-test runtime/UI/journal suite passed**; the request,
  provider and backend suite then passed **62 tests**. Touched-file Ruff F/E9
  passed. These results are separate from the full gate below.
- The initial full report, `evidence/CETA_OFFLINE_REQUESTS_20260927.json`, is
  preserved: **520 tests run, four failures, one environment skip**, no errors.
  Two failures were stale native hardware probe fixtures: they lacked explicit
  serializable request metadata and expected the old probe argument shape.
  Fixtures now assert the prepared messages, observed profile and dispatch hook.
  Two were a real terminal cancellation defect caused by cached authority inside
  the polling interval. The source now refreshes authority at completion; tests
  hold the monotonic clock fixed to make this race deterministic. All four focused
  regressions pass after repair. These failures are classified **fixed now**.
- Final full gate: `evidence/CETA_OFFLINE_REQUESTS_FINAL_20260927.json`,
  **520 tests run, 519 passed, one environment skip**, zero failures/errors.
  The skip is the same unavailable distinct Windows short alias as the first
  increment. Tested source remained unchanged, with SHA-256
  `eedf574eef6fbaa0976ba65a2431c4d863443a2ff48ee22a3d978c5a1597765f`.
  Touched-file Ruff F/E9 and `git diff --check` passed after the repairs.
- Source manifest/checksum regeneration, both builders' `--check` modes and
  `scripts/verify_package.py` passed with **344 registered payload files**.
  Final documentation updates are included by rerunning those same checks.
- `evidence/CETA_OFFLINE_REQUEST_UI_20260927.png` was visually inspected. It shows
  the captured file, retained composer and explicitly estimated allocation. This
  is a synthetic prepared-request capture, with no model inference. The existing
  Windows font was loaded only into the offscreen test process, as in the first
  increment; no product/host font changes were made.

Hardware inspection already runs on the computer executing CETA and begins each
window with no cached hardware readiness. RAM/GPU observations and model fit
suggestions are estimates. The required backend/device/memory binding, measured
capability selection and full installed offline workflow remain unfinished.
Neither this machine's readings nor the synthetic test profiles are production
defaults for a different installing computer.

## Third increment: backend-specific loading admission (W03)

Implemented source paths:

- New `src/ceta_desktop/backends.py` inspects the explicitly selected llama-server
  executable's version, required command-line controls and actual backend device
  inventory. Inspection binds executable hash, relevant environment digest and
  a short validity window. Probes have cancellation, output and time limits and
  terminate only their own child process. Executable/library authenticity and
  compatibility qualification remain part of managed runtime delivery.
- Owned GGUF startup verifies the installed asset, reads bounded GGUF v2/v3 scalar
  metadata and performs fresh hardware inspection after the expensive steps.
  Unknown RAM blocks loading. The chosen GPU must occur in that executable's
  device list and match one unambiguous dedicated-memory hardware identity.
  Shared/integrated memory, unknown/RPC device types and pooled devices cannot
  justify a GPU plan. A separately fitting CPU plan remains available, with
  GPU/KV/operation offload explicitly disabled. An unreadable device inventory
  permits only this CPU fallback, with its inspection error retained.
- The selected launch records the executable/model hashes, observed device and
  memory, environment identity and exact arguments in the governed application
  journal. `model.inspect` is a registered operation distinct from `model.start`.
  Arguments bind one device, one parallel slot, 4096 context tokens, explicit
  batch/cache/offload settings and disabled automatic fit adjustment. Inherited
  `LLAMA_ARG_*` and RPC defaults are removed from inspection/launch environments.
  Changed executable/environment, stale inspection, cancellation or changed UI
  selection/endpoint rejects launch. Process error/exit clears the active plan.
- Loading estimates now expose weights, KV/cache, backend workspace and host
  staging separately. Dense llama/qwen2/qwen3 metadata supports a full-context
  f16 KV calculation; unknown metadata retains a disclosed size-based allowance.
  All estimates remain unverified, and no OS allocation reservation is claimed.
  Dedicated GPU and host staging budgets are checked separately.
- External Ollama loading no longer borrows an unrelated GPU's fit estimate.
  A new load must fit measured host RAM, because CETA has not bound that external
  service to a compatible GPU. The service still selects actual placement. Reuse
  of an existing allocation requires the same nonempty reported digest and enough
  reported context, plus free RAM headroom. Missing/mismatched resident identity
  cannot bypass admission. Residency does not establish backend quiescence.
- Model memory metadata/size are included in prepared request identity checks.
  Provider results retain the actual resource assessment used at dispatch, with
  its explicit estimate and external-placement limitations.

Validation and discovered issues:

- Initial focused backend/readiness/native suite: **49 run, one test error**. The
  new assertion read `arguments` from the wrong journal level; using the existing
  `consequence.arguments` contract repaired it. Classification: **fixed now**.
- Integrated backend/readiness/native/prepared-request/merged-task suite:
  **87 tests passed**; touched-file Ruff F/E9 passed at that point.
- Additional memory-pressure, multi-GPU, GGUF array/duplicate-key and native
  GPU/stale-endpoint cases: **25 focused tests passed**. Ruff then found two
  duplicate copies of new test methods introduced by patch application. Removed
  only those duplicate copies and repeated touched-file Ruff F/E9: **passed**.
  Classification: **fixed now**, without weakening or dropping distinct cases.
- Full source report: `evidence/CETA_OFFLINE_BACKEND_ADMISSION_20260927.json`,
  **537 tests run, 536 passed, one environment skip**, zero failures/errors.
  The skip remains the unavailable distinct Windows short alias. Source did not
  change during the gate; all 207 attributed files match afterward. Source SHA-256:
  `edc6ded1ce6817a8a99c8419ac26fed680df4d0269cb742b7285e507c532bc1d`.
  `git diff --check` passed.
- Read-only installed-backend check found the standard local Ollama executable
  and client version **0.34.3**. It reported no connected service; a bounded GET
  to `127.0.0.1:11434/api/version` failed with Windows connection refusal 10061.
  Classification: **environment/runtime unavailable, not blocking source work**.
  Live API/inference compatibility is unverified. No service was started, no
  global settings changed and no model was loaded or downloaded by this check.

The backend controls and device-output parser were checked against the official
[llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
and [device enumeration implementation](https://github.com/ggml-org/llama.cpp/blob/master/common/arg.cpp)
on September 27. The selected executable must independently expose the required
controls; current upstream docs alone do not qualify an installed binary.

This increment addresses F04/F05 admission paths in source. It does not complete
W03: managed immutable assets, library/runtime qualification, exact tokenizer
integration and real hardware/load observations remain. W04 must still bind owned
endpoint identity/health, shared leases and uncertain cancellation across restart.
Generic external services retain their disclosed advanced/unqualified status.

## Fourth increment: shared runtime coordination (W04, in progress)

Added `src/ceta_desktop/runtime_coordination.py` and integrated it with actual
local transport, prepared-request metadata checks, provider results and native
Models/Chat controls. This is request coordination, separate from task authority.

- Loopback host aliases and URL prefixes on the same port share an OS-released,
  nonblocking file lock across cooperating CETA processes in the same Windows
  account. Separate `--data-dir` choices do not create extra capacity. Other
  applications/users remain outside this coordination boundary.
- Before generation bytes are sent, a durable record marks the dispatch in flight.
  Completed protocol terminal events permit another request. Cancellation, broken
  transport, malformed/truncated output or a process crash without such an event
  retains uncertain backend state across app restart; releasing the lock does not
  clear it. Metadata failures before dispatch do not create fake uncertain effects.
  State contains request/runtime/process observations, never prompts or responses.
- Windows process creation time protects against PID reuse. Dispatch observes the
  process owning the actual accepted TCP connection, rather than assuming the
  current listening PID necessarily owns an earlier connection. Native IPv4 and
  IPv6 ownership are tested. Unsupported/inaccessible observations stay unknown.
- Native **Recheck runtime** records observations through the governed application
  path. It cannot clear uncertainty merely from residency, acknowledgment, listener
  disappearance or server restart. Ollama/generic services may leave separate
  model workers alive. The current recheck records that the original server ended
  while retaining uncertainty; conclusive owned-worker shutdown/restart and a
  qualified backend recovery policy are still required to finish W04.
- Chat distinguishes stopped output from unconfirmed backend termination. A new
  preparation checks the shared state before the composer is consumed. Recheck
  results from an older endpoint do not replace status for current settings.
- HTTP metadata, nonblocking connection, bounded writes and reads use cancellation
  and absolute deadlines; typed transport deadlines map to `timed_out` even before
  the provider monitor next polls. Hardware inventory/context work still needs the
  remaining end-to-end deadline integration. No caller cancellation event is reset.

Validation underway is recorded in the dedicated coordination reports. Independent
tests cover two processes, loopback aliases/prefixes, process crash, a server that
continues after client cancellation, protocol completion, corrupted state, native
process exit/PID identity, stale UI results and transport deadlines. Native fixture
inspection exposed the uv launcher's child interpreter: the test now starts the
base interpreter directly and checks the actual listening PID. This was a fixture
correction; the native ownership query correctly identified the listener.

The implementation does not yet provide the full owned runtime lifecycle. Next
work must include owned endpoint health/identity, process-tree shutdown/restart,
usable recovery after uncertain cancellation, resident-model switching/unload and
the remaining non-HTTP deadline stages. Those remain part of the original goal.

Validation and repaired issues:

- Existing transport/readiness/prepared-request checks: **44 tests passed**.
  The initial new coordination suite ran 11 tests with one incorrect launcher-PID
  assertion; the actual interpreter launch repaired it, and all 11 then passed.
  A separate process lookup confirmed the earlier short-lived fixture had ended.
- Integrated coordination/readiness/prepared-request suite: **52 tests passed**;
  native/request/merged-runtime suite: **75 tests passed**. Touched-file Ruff F/E9
  passed. HTTP fixtures tolerate only expected disconnect errors after intentional
  client cancellation, rather than logging those as unexpected server crashes.
- First full gate, preserved as
  `evidence/CETA_OFFLINE_RUNTIME_COORDINATION_20260927.json`: **551 tests run,
  two failures, one environment skip**, no errors. Two new coordination fixtures
  accidentally inspected live host RAM, so their synthetic model was correctly
  refused under memory pressure before the expected HTTP dispatch. They now inject
  synthetic memory consistently. Classification: **fixture issue, fixed now**.
- An additional independent overlap reproduction showed two providers sharing one
  client could let a rejected second request clear the first one's terminal
  observation pointer. A nonblocking client-operation guard now preserves the
  active request/metadata state in addition to the endpoint-wide lease. The new
  regression confirms one dispatch, rejection of overlapping generation/profile
  inspection, and an idle state after the first request's actual terminal event.
  Classification: **product race, fixed now**.
- Final focused coordination suite: **13 passed**; touched-file Ruff F/E9 passed.
  Final full gate: `evidence/CETA_OFFLINE_RUNTIME_COORDINATION_FINAL_20260927.json`,
  **552 run, 551 passed, one environment skip**, zero failures/errors. The skip is
  the unavailable distinct Windows short alias. All 209 source-attributed files
  remained unchanged during/after the run; source SHA-256
  `764effcf845f3b83be213ea122f804561b94fb1404d717a7b39194b5a5e919ca`.
  `git diff --check` passed.
- Native diagnostic capture:
  `evidence/CETA_OFFLINE_RUNTIME_COORDINATION_UI_20260927.png`. The Recheck control
  is visible, but the offscreen render clips the hardware summary/detail text.
  This is **not a visual pass**. Classification: **requires follow-up UI repair**
  within the goal, before installed/UI qualification. Use a settled-layout test
  with an explicitly available font and fix label/layout sizing without hiding
  the fit limitations. The capture used temporary synthetic app data and an
  explicitly loaded existing Windows font; no runtime/model was started and no
  hardware defaults or fonts were written into the product.

Windows ownership calls were checked against Microsoft's
[TCP table API](https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-getextendedtcptable)
and [process creation-time API](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes).
These native tests establish observation mechanics, not independent proof that an
external service has terminated every model worker or cannot forward requests.

## Fifth increment: owned Windows runtime lifetime (W04, in progress)

The status review rehashed the fourth-increment source before editing; it exactly
matched that report's source SHA-256. The full product was partially implemented,
not complete. This increment continues the same checkout and authorization.

- Added `windows_job.py` and the native `owned_process.py` event-loop adapter.
  Windows runtime creation is suspended. Assignment to a new non-inheritable job
  with kill-on-close and neither breakaway flag, plus durable registration under
  the endpoint lease, must succeed before the primary thread is resumed. A failed
  assignment/registration terminates the suspended child without executing it.
- Startup rejects an occupied endpoint or an already starting owned runtime.
  Before generation transmission, the actual endpoint process identity must be a
  member of its saved job. An unrelated replacement cannot inherit that admission.
  CPU/GPU resource admission and actual model readiness remain separate checks.
- The Windows native model path now uses this adapter through existing governed
  model start/stop actions. Start observations include containment; finish
  observations include the job's zero-active-process result. Workload execution
  remains on its existing process path. Non-Windows model startup retains its
  existing unqualified process behavior.
- Stop terminates the whole owned job. If the root exits while descendants remain,
  polling terminates those descendants and waits for zero active processes before
  reporting completion. Window closure remains pending if shutdown is unconfirmed.
  Pipes and retained output are bounded; process/query errors are not completion.
- Recovery reopens only the saved random job name. Zero members or absence of that
  previously observed kill-on-close job permits the recorded interrupted request
  to become idle. Access errors, changed limits, or live workers retain uncertainty.
  A fresh app instance can recover after the prior owning process crashes.
- The usable manual sequence is Stop local model, Recheck runtime, then Start.
  This does not automatically restart or certify HTTP/model readiness. External
  services still cannot clear uncertainty based only on a listener PID ending.

This is lifetime control for members of a Windows job, not a hostile-executable
sandbox. Brokered processes (including WMI launch), remote work, runtime provenance,
and backend worker behavior require separate qualification. The native API behavior
was checked against Microsoft's [job documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
and [limit flags](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information).
The installed PySide6 6.11.2 binding exposes no Windows process-argument modifier;
the adapter therefore uses CPython's Windows creation primitive with an explicit
handle list and retains the primary thread handle until assignment. That path
still needs qualification in the frozen installer.

Validation and issue classification:

- Initial native containment tests: seven run, five passed, two errors. The Python
  zero-length `PeekNamedPipe` call returns two values, not three. Corrected the
  read path; all seven passed. Classification: **fixed now**. Failed fixtures
  closed their owned jobs; no model runtime was used.
- Existing GUI/merged-runtime checks plus layout check: **47 passed**.
  Owned/coordination integration: **24 passed**. Extended crash/recovery/native
  adapter plus hardware UI checks: **28 passed**. Touched-file Ruff F/E9 and
  `git diff --check`: **passed**.
- The prior clipped screenshot was a layout-timing diagnostic. Loading the real
  Windows UI font before window construction and waiting for the layout to settle
  gives full label heights and readable text. Added geometry checks at 1100x720
  and 1440x1080. The new capture
  `evidence/CETA_OFFLINE_OWNED_RUNTIME_UI_DIAGNOSTIC_20260927.png` was visually
  inspected and the two descriptions are readable. Classification: **measurement
  issue isolated; settled-layout regression added**. No product text was removed
  and no speculative layout change was made. This one capture is not full UI or
  installed-product qualification. It uses synthetic hardware and temporary data.

- The first full gate is preserved in
  `evidence/CETA_OFFLINE_OWNED_RUNTIME_20260927.json`: **566 run, four failures,
  one environment skip**, no errors. Two new crash helpers and two existing
  coordination helpers depended on an inherited `PYTHONPATH`; the supported
  direct verification command did not provide it. Their child interpreters could
  not import `ceta_desktop`. The fixtures now supply this checkout's source path
  explicitly, without inheriting an unrelated project's import path. Corrected
  owned/coordination tests run without inherited `PYTHONPATH`: **27 passed**;
  touched Ruff F/E9 passed. Classification: **fixture environment issue, fixed
  now**. The failed report is retained. Child cleanup closes pipes and waits for
  each owned helper.

- Final gate: `evidence/CETA_OFFLINE_OWNED_RUNTIME_FINAL_20260927.json`,
  **566 run, 565 passed, one environment skip**, zero failures/errors. The skip
  remains the unavailable distinct Windows short-path alias. All 212 attributed
  source files were unchanged during the run and rehashed identically afterward;
  SHA-256 `3c81e8b7d74e77efb2649b5e22e8a3b281a299f6696a577b1352a2253b851845`.
  Source manifests/checksums are regenerated and checked after these record edits.

No actual model inference, managed installation, new installer build, signing or
public release is established by these process fixtures. The complete goal stays
active, including the remaining packages below.

## Sixth increment: owned health, restart and explicit model unload (W04)

Continued the full active goal after the prior verified lifetime-control increment.
Same repository/branch/baseline; prior changes and evidence were preserved.

- Owned Windows startup automatically checks Ollama version/catalog or llama.cpp
  health/catalog under an absolute deadline. Every accepted TCP connection must
  belong to the expected job before metadata bytes are sent. Startup connection
  failures and HTTP 503 loading states can be retried; malformed metadata, wrong
  ownership, cancellation and deadlines do not become readiness. The UI says
  service healthy, with inference/capabilities still unverified. No prompt is sent.
- Health observations use the existing governed `model.inspect` operation and are
  bound to the start action, job, endpoint and current run. Late callbacks cannot
  update newer settings. A failed health check stops the owned workers. Catalog
  refresh retains an existing manual model choice even if it disappeared.
- Added explicit **Restart owned runtime**. It waits for confirmed job shutdown
  before another start; the startup lease performs the ended-job reconciliation.
  Stop failure, changed settings, active local operations and endpoint admission
  prevent unsafe continuation. Stop/close cancels queued restart. GGUF restart
  reuses the explicit executable/pack selection but repeats byte inspection and
  fresh hardware planning. No external service is automatically restarted.
- Added **Inspect loaded models** and **Unload selected resident**, backed by a
  registered `model.unload` application action. A snapshot expires after 60 seconds
  and is bound to the endpoint and observed process creation identity. Dispatch
  rechecks local model identity and resident digest. The exact selected model is
  sent an empty `keep_alive: 0` unload request; no model files are deleted and no
  replacement model is automatically loaded. The chosen active model is retained.
- Unload shares the endpoint lease with chat/probe across cooperating processes.
  It records `operation: unload` before transmission and requires the expected
  terminal acknowledgment plus a new residency observation. Interrupted, malformed,
  timed-out or unobserved completion stays uncertain. Existing uncertain inference
  blocks unload rather than being cleared by its acknowledgment. External clients
  and mutable aliases can change independently; the API has no atomic digest-bound
  unload transaction. The UI discloses that unloading may affect other clients.
- Selected Windows backend inspection commands now use the same suspended-start
  job lifetime control. Output, cancellation and time bounds cover ordinary child
  workers, including a parent that exits before them. Non-Windows behavior remains
  explicitly unqualified; manual connect instructions are retained there.

The protocol checks use the official [Ollama API](https://raw.githubusercontent.com/ollama/ollama/main/docs/api.md)
and [llama.cpp health API](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).
Documentation alone does not qualify an installed backend.

Verification completed before the full gate:

- Existing readiness/native/merged/hardware suite: **87 passed**.
- New health/restart suite: **10 passed**, before unload cases were added.
- Extended lifecycle/unload plus transport/coordination: **56 passed**.
- Contained inspection, owned runtime, lifecycle and hardware UI: **58 passed**.
  Includes a real temporary child process killed by an inspection deadline.
- Touched Ruff F/E9 and `git diff --check`: **passed**.
- `evidence/CETA_OFFLINE_RUNTIME_LIFECYCLE_UI_20260927.png`: visually inspected
  settled 1440x1080 native capture. Restart, residency controls and hardware text
  are readable. This uses synthetic hardware/data and does not establish inference
  or full installed UI qualification.

Real backend service check:

- Added reusable `scripts/verify_owned_service.py --executable <ollama.exe>
  --report <new-file.json>`. It uses an empty temporary Windows profile, model
  store and coordination directory, plus a separately selected loopback port.
  Child-only environment overrides do not change global settings. The owned Qt
  adapter and actual HTTP health method are used for two start/stop cycles.
- Initial report `evidence/CETA_OFFLINE_OLLAMA_SERVICE_20260927.json` passed.
  Final report after source cleanup:
  `evidence/CETA_OFFLINE_OLLAMA_SERVICE_FINAL_20260927.json`, **passed twice** with
  actual runtime version **0.34.3**, zero installed models, distinct job identities,
  zero active job members after shutdown and successful ended-job recovery.
  Each cycle recorded 14 total processes associated with the job over its lifetime.
- Executable SHA-256:
  `f282bab3cb8ece9f1843811c08e54fec449557efadc49ee0f9af07f1b93407fc`.
  Final tested source SHA-256:
  `d39e96aa44547c90a11b2fba39cd90a12b55937be8b15bee540bd6806ad3143c`.
  Source remained unchanged during each run. The reports retain their own hashes;
  the first report is not relabeled as final-source evidence.
- **No model load/inference/download and no OS network isolation** occurred.
  This qualifies the observed installed service metadata/lifetime path only, not
  generation cancellation, resident unload with real weights, GPU acceleration,
  dependent libraries, the frozen app or offline product readiness.

- Final full-source gate: `evidence/CETA_OFFLINE_RUNTIME_LIFECYCLE_20260927.json`,
  **583 run, 582 passed, one environment skip**, zero failures/errors. The skip
  remains the unavailable distinct Windows short-path alias. All 214 attributed
  source files remained unchanged; rehashing after the run matches both this gate
  and the final real-service report at the SHA-256 above. Source manifests and
  checksums are regenerated and checked after final documentation edits.

Remaining W04 work
includes whole-request hardware/context deadlines and real-model/frozen-backend
qualification. W03 exact tokenization/immutable assets and the original managed
setup, capability, archive, offline/install/release and training work remain open.

## Seventh increment: pinned managed runtime acquisition (W05, initial W06)

The preceding status turn made no implementation progress. Rechecked the actual
checkout, dirty state and recorded source hashes, then advanced the managed setup
path. Whole-request deadlines and every original work package remain in scope.
No additional project content was transferred.

- Added a bundled `runtime_catalog.json` for official Ollama **0.34.3 Windows x64**.
  Retrieved release metadata from the official GitHub API and downloaded the
  standalone archive into ignored CETA build data. The archive's **1,460,962,639
  bytes** match official SHA-256
  `306ce9e81e3491d147f558e60d7a389499f244d10f71859c6e4e899241d1b4ae`.
  The catalog pins all **82 extracted files**, totaling **1,929,045,302 bytes**,
  including the executable, CUDA/Vulkan/CPU libraries and bundled license notices.
  The pinned upstream Ollama MIT notice is included unchanged in the catalog.
- `runtime_installation.py` provides explicit download/resume and offline import.
  Downloads permit only the exact release URL and its official HTTPS asset host;
  ambient proxies/credentials are not inherited. Resumed responses must match the
  requested byte range and complete pinned size. The whole archive is rehashed
  before extraction, and each extracted file must match the bundled catalog.
  ZIP paths, collisions, symlinks, unexpected/missing files and size mismatches
  fail before publication. Disk admission budgets both archive and extracted bytes.
- An OS-released acquisition lock prevents cooperating CETA processes from writing
  the same installation simultaneously. Interrupted downloads remain resumable.
  Offline imports are copied into CETA's own staging and reverified. Existing
  versions, unknown files, failed copies and abandoned staging are preserved;
  no automatic destructive cleanup or overwrite is performed. Publication uses a
  distinct version/digest directory. Existing installations are rehashed rather
  than trusted through a saved receipt. Corrupt installed files block reuse.
- Models now includes **Download / resume runtime**, **Import runtime ZIP**,
  **Pause**, **Start managed runtime**, and **Runtime licenses** controls. Actions
  are background operations registered as `runtime.install`, `runtime.import`,
  and `runtime.inspect`. Opening the app does not download, import or start it.
  Acquisition alone never starts executable code or downloads a model.
- Managed startup checks all pinned files and refreshes this executing computer's
  hardware. A private child environment uses a separate model store/profile and
  loopback port 11435, with cloud features disabled, one request/loaded model and
  context 4096. Only selected Windows system variables are inherited; user PATH,
  model paths, GPU overrides and unrelated credentials are not passed through.
  Existing Ollama remains an explicit separate path at its existing port.
- Managed restart repeats file/hardware checks. Settings changes/cancellation
  during verification prevent launch. HTTP health must report the pinned version;
  disagreement stops the owned runtime. Health remains distinct from inference.
  The desktop build now explicitly includes the catalog resource.

Sources: [official release](https://github.com/ollama/ollama/releases/tag/v0.34.3),
[standalone Windows packaging](https://docs.ollama.com/windows),
[pinned MIT license](https://raw.githubusercontent.com/ollama/ollama/v0.34.3/LICENSE).
This is a pinned baseline, not a claim that this is the newest or fully qualified
runtime. Optional ROCm/MLX companion archives have not been integrated or qualified.

Verification and issue classification:

- Initial acquisition tests: **15 passed**. Initial combined source/native run:
  **53 run, one error** because a new test looked for journal `operation` instead
  of the existing `kind` field. Corrected the assertion; classification **test
  fixture issue, fixed now**. Broader acquisition/native/lifecycle/hardware/GUI/
  merged/distribution regression run: **112 passed**. Final focused acquisition
  and native setup checks: **26 passed**.
- Used the actual new offline importer against the official archive in
  `build/managed-runtime-qualification-v0343/data`. All 82 files verified after
  extraction. No model files or personal Ollama data were read or modified.
- An actual final-1024-byte range request through the new download transport
  returned HTTP 206 with the exact requested range; bytes matched the verified
  archive. Complete resumable-transfer failure cases use deterministic fixtures.
- Full source gate: `evidence/CETA_OFFLINE_MANAGED_RUNTIME_20260927.json`, **609
  run, 608 passed, one environment skip**, zero failures/errors; 167.135 seconds.
  Skip: unavailable distinct Windows short-path alias. All **219 attributed source
  files** remained unchanged during the run.
- `evidence/CETA_OFFLINE_MANAGED_SERVICE_20260927.json`: the real imported runtime
  passed **two** owned start/health/stop cycles using the managed child environment
  and an empty temporary profile. Version 0.34.3 matched the catalog; all 82 pinned
  files verified; both shutdowns reported **zero active job processes**. No model
  was downloaded or loaded; no inference or OS network isolation occurred.
  `scripts/verify_owned_service.py --managed-data-dir <directory>` now supports
  this repeatable check with the same environment constructor as the application.
- Both reports bind source SHA-256
  `3c811e8c804aaf9dddb387046ad54d40412977ce3083a102e168be8bf5ac677f`.
  Touched Ruff F/E9 and `git diff --check` passed. Native capture
  `evidence/CETA_OFFLINE_MANAGED_RUNTIME_UI_20260927.png` was visually inspected at
  1440x1080; the new controls and descriptions are readable. It uses synthetic
  hardware and temporary data, not a real-model or installed-app qualification.
  The full product goal remains active; no new installer, signing or publication.

Remaining limits: file checks are observations before launch, not a protected
lifetime binding against same-account writes. Loaded driver/library provenance,
real model inference, GPU use, frozen packaging, OS network isolation and other
hardware still require qualification. Network reads currently use a five-second
socket timeout; the original two-second cooperative cancellation target and
whole-request deadlines remain open. Failed extraction staging can consume disk;
an explicit discard/repair workflow is still required. Managed model acquisition,
immutable model identities, exact tokenization and full guided setup are next.

## Eighth increment: managed models and real local generation (W05/W06/W04)

Continued the full goal after verified managed-runtime progress. Rechecked the
same root/branch/HEAD and preserved all prior work. The new model assets came
from the official Ollama registry into this CETA project's ignored build data;
no other project's models, conversations or configuration were imported.

- Added `model_catalog.json` with six pinned Qwen3 Q4_K_M choices: 0.6B, 1.7B,
  4B Instruct, 8B, 14B and 32B. Each pins the exact raw manifest and every model,
  configuration, template, parameter and license blob. License text is available
  before download. Candidates and hardware estimates do not establish quality.
- Added `model_installation.py` download/resume, verification, offline ZIP export
  and import. Downloads address exact blob digests, with an exact official registry
  and digest-bound CDN redirect policy; mutable tags are not queried at install.
  Files publish under CETA's private model store only after hashing. The versioned
  model manifest is exposed after all referenced files verify. Interrupted blobs,
  unknown files and corrupt assets are preserved; corrupt existing bytes block
  reuse rather than being silently overwritten. Resume disk admission accounts
  for already staged bytes. Model ZIP directory allocation, members, sizes, paths,
  duplicates, split archives and links are bounded/rejected before extraction.
- Offline export creates a new ZIP only, retaining original manifest and license
  blobs; source mutation fails the export. Import on another computer checks that
  installation's bundled catalog and makes no registry call. It transfers model
  files only, with no conversations, authority, hardware observation or readiness.
- Models has candidate selection, download/resume, import/export, license, pause,
  and **Use and test model** controls. Opening it does not download or infer. A
  fitting balanced candidate is preferred (4B, then 1.7B, then 0.6B), while larger
  fitting choices remain available. The older hardware suggestion follows the
  same preference policy instead of always selecting the largest. Manual choices
  survive a fresh hardware assessment, but previous readiness is never restored.
- Selecting a managed model rehashes its files, binds metadata requests to the
  owned job, and compares the service's model digest with the pinned manifest
  before changing the active model. Selection then performs the explicitly
  requested short governed probe. Its status is shown in the setup panel, and
  the pause control remains attached through the verification-to-probe handoff.
  Cancellation shares the worker event from the start rather than replacing an
  event after the worker begins. Owned chat/probe connections now also check job
  membership. External runtime configuration is unchanged.
- Managed runtime environment sets `OLLAMA_NOPRUNE=1`, preserving blobs from
  interrupted acquisitions instead of letting startup remove them. Added
  `model.export` as a registered application action. The frozen build includes
  the model catalog resource. Normal first-launch orchestration is still pending;
  these controls provide the explicit managed runtime/model path in Models.

Sources: [official Qwen3 model](https://ollama.com/library/qwen3:0.6b-q4_K_M),
[pinned runtime model storage/publication code](https://raw.githubusercontent.com/ollama/ollama/v0.34.3/server/images.go),
[name/path format](https://raw.githubusercontent.com/ollama/ollama/v0.34.3/types/model/name.go),
[startup pruning option](https://raw.githubusercontent.com/ollama/ollama/v0.34.3/envconfig/config.go).
Storage layout is deliberately qualified against the pinned runtime version;
changing runtime versions requires requalification.

Verification:

- Acquisition/runtime unit checks: **33 passed**. Managed models, runtime controls,
  hardware and request checks: **78 passed**. Extended native model setup/handoff,
  acquisition, runtime, hardware, lifecycle and request regressions: **81 passed**.
  Touched Ruff F/E9 and `git diff --check` passed.
- Downloaded the actual pinned Qwen3 0.6B model: **522,653,767 bytes across five
  files**, manifest SHA-256
  `7df6b6e09427a769808717c0a93cadc4ae99ed4eb8bf5ca557c90846becea435`.
  The real downloader verified every blob before publishing its private alias.
- Added reusable `scripts/verify_managed_model.py --data-dir <isolated-data>
  --model qwen3-06b --report <new-report.json>`. It makes no downloads and uses
  synthetic prompts with the actual `TaskRuntime`, `LocalProvider`, local HTTP
  client, owned process adapter and private managed environment.
- `evidence/CETA_OFFLINE_MANAGED_MODEL_REAL_20260927.json` **passed all ten
  lifecycle observations**: owned health, governed local probe, governed chat,
  resident unload, cancellation, zero-worker shutdown, ended-job reconciliation,
  restart health, another local probe, and another zero-worker shutdown. Chat
  answered the synthetic arithmetic question with a completed response. Cancel
  preserved partial output and `backend_state: uncertain`; owned shutdown and
  reconciliation cleared that uncertainty before the next successful request.
- Runtime residency reported 4096 context tokens and **zero VRAM use**. This is
  observed CPU-path evidence on one Windows computer, not GPU or cross-hardware
  qualification. The evidence records that machine's actual RAM/GPU separately;
  none of those observations are used as defaults in the catalogs or application.
- The 0.6B model returned visible text but did **not** match the requested
  `CETA_READY` instruction. Classification: **quality limitation observed; W07
  capability evaluation still required**. The probe verifies response liveness,
  not instruction-following quality, and the UI explicitly states this limit.
- The real run's source SHA-256 is
  `3ef2bd1afc62afd822d330e247d4ac41d32294f206d31e41587777c13d6b99a0`.
  All **225 attributed source files** still match this identity after the checks
  below. No OS network isolation, frozen app, installer or public release was
  qualified by this source run. The full goal remains active.
- Full source gate `evidence/CETA_OFFLINE_MANAGED_MODELS_20260927.json`:
  **629 run, 628 passed, one environment skip**, zero failures/errors; 164.438
  seconds including gate overhead. Skip: the temporary volume does not provide a
  distinct Windows short-path alias. Source remained unchanged during the run.
- `evidence/CETA_OFFLINE_MODEL_ROUNDTRIP_20260927.json` **passed** actual pinned
  model export and import into a separate CETA data directory. The downloader
  was forbidden during import; this is transport-free import evidence, not OS
  network isolation. ZIP size **522,655,999 bytes**, SHA-256
  `3a6983f4b1f044437324208368c67cd706577ab2ae9d2793e24535f2f2d5bb1e`.
  Imported model files reverified successfully. Both this report and the full
  gate match the real inference report's source identity above.
- Native capture `evidence/CETA_OFFLINE_MANAGED_MODELS_UI_20260927.png` was
  visually inspected at 1440x1080. The runtime/model controls, candidate estimate
  and untested capability status are readable. It uses synthetic hardware and
  temporary data; it does not establish inference or installed-app acceptance.
  Delivery notes, dependency notices and continuity are updated. Source package
  manifests/checksums are regenerated and checked after these record edits.

Remaining work includes lifetime asset binding against same-account mutation,
exact tokenization, end-to-end deadlines, failed-stage repair/discard, guided
first launch/skip/restart journeys, measured capability observations, actual GPU
lanes and the original archive/offline/installer/release/training packages.

## Ninth increment: guided native setup (September 28, W06)

The previous turn completed the managed model evidence and source-package checks;
classification: progress. Continued the same full offline-product objective in
the same checkout/branch/HEAD, preserving prior work and evidence. No personal
project material crossed the repository boundary.

Added `pages/local_setup.py`, `tests/test_desktop_local_setup.py`, and the actual
native-journey harness `scripts/verify_guided_setup.py`. `app.py` integrates a Chat
entry card and a persistent Models guide with the existing seven-page shell.
Normal setup requires no typed model tag, endpoint or executable path. Explicit
existing-service controls still use the configured local endpoint.

The guide inspects hardware/disk asynchronously, presents at most three estimated
candidate choices, discloses exact catalog download sizes, storage location,
context, sources and licenses, and combines acquisition, re-verification, owned
startup/health and the governed probe behind **Install and test**. Offline setup
accepts the trusted runtime ZIP plus a pinned CETA model ZIP. **Recheck installed
setup** does not download. Asset actions retain their existing registered authority
and journal path; no second inference path was added.

Setup supports skip, explicit existing-service discovery/testing, preserved partial
transfers and retry, saved model preferences and fresh checks after restart. It
does not persist readiness. Setup locks competing model controls and retains chat
drafts without dispatching them while changing the runtime. Pause carries through
acquisition/health/model selection/probe; late results cannot start another stage
after cancellation. An owned setup stops its workers on cancellation; an external
service remains independent. Owned health now binds cancellation before the worker
begins rather than replacing its event after startup. Test results are ephemeral
and invalidated by settings changes or owned runtime completion.

Validation so far: existing native setup/hardware/navigation regression **35
passed**. Initial new guided run: **11 run, one failure** at the six-second fixture
wait on repeated offline recheck. Diagnostic polling of that same journey showed
the still-live worker completed in **7.015 seconds**, with both tests successful;
classification: test timing issue, fixed now. The test wait is 15 seconds for the
complete repeated governed fixture; no production timeout or completion condition
was relaxed. Added a draft-preservation check. Combined guided/native/model/runtime/
lifecycle/hardware/navigation regression: **63 passed**. Touched Ruff F/E9 passed.

`evidence/CETA_OFFLINE_GUIDED_SETUP_REAL_20260928.json` passed the actual native
journey in a new isolated data directory using the already pinned runtime/model
archives. Both download transports were forbidden; only the file-dialog inputs
were supplied by the harness. Hardware inspection, native orchestration, assets,
owned workers, HTTP health and governed inference were real. The first response
completed in 2.703 seconds. Closing confirmed zero active owned workers. Reopening
retained `qwen3-06b` as a preference but restored no hardware/readiness result.
**Recheck installed setup** then completed another response in 2.093 seconds, and
closing again confirmed zero workers. All 82 runtime and five model files verified.
Both responses reported zero VRAM use: this is the observed CPU path only. The
responses did not both follow the exact probe instruction; quality remains
unqualified. No personal conversations or project content were used.

`evidence/CETA_OFFLINE_GUIDED_SETUP_UI_20260928.png` was visually inspected at
1440x1080: candidate, sizes, location, memory observation, actions and completed
short-test limitations are readable. It captures the actual source UI and model
run, not a frozen/installed application. The harness forbids CETA's two download
transports; it does not impose OS network isolation on the runtime or computer.

The real journey binds source SHA-256
`b6a22f3a61b9de7c5072a5ffae27a736d742391e96f4ad016297e490690ddcf4`.
The full gate `evidence/CETA_OFFLINE_GUIDED_SETUP_20260928.json` passed: **641 run,
640 passed, one environment skip**, no failures/errors, 184.875 seconds including
overhead. The temporary volume lacks a distinct Windows short-path alias. All
**228 attributed source files** stayed unchanged during the suite and match the
real native journey above. Source manifest/checksum checks and package verification
are refreshed after the documentation edits. This increment does not complete
W03/W04/W05/W07 qualification or the frozen/offline/installer gates.
Further setup refinement includes explicit unavailable-hardware presentation after
a previously successful observation and qualified candidate/performance labels.
These presentation refinements do not bypass the current unknown-memory rejection.

## Tenth increment: rendered token counts on the owned model worker (2026-09-28)

The previous status-answer turn rechecked existing source/evidence but changed no
implementation; classification: no progress. This turn resumed the full objective
in the same CETA checkout, preserving dirty/untracked work and historical reports.
No other personal project's content was transferred.

Added `request_tokens.py` and connected it to `LocalProvider`, task preparation,
request allocation and the native preview. The managed path verifies the pinned
runtime/model files, checks the supported tokenizer special-token behavior, and
uses Ollama 0.34.3's actual render-only handler with truncation disabled. Rendering
can load weights, so it uses fresh memory admission, cancellation and the durable
runtime lease. Interrupted or malformed rendering remains uncertain. Discovery
reads Windows listener/process metadata; only the unique matching llama-server
image in CETA's owned job receives tokenizer requests. Connections recheck exact
process identity/job membership before transmitting text.

The count includes the rendered template and special tokens, reserves output and
one unused context slot, and binds message/template hashes, model digest, context,
runtime archive and worker identity into the prepared receipt. Allocation still
prioritizes mandatory instructions/current input, selected sources, then paired
recent history. Oversized mandatory input is refused before consuming the draft.
Dispatch rechecks worker/model/context and payload binding. Every Ollama completion
disables silent prompt truncation and context shifting, and a reported evaluation
count mismatch fails the response. Unsupported/external configurations retain an
explicitly unverified estimate. Counted tokens do not establish model quality,
GPU support or protection against subsequent asset mutation.

Contract references: [pinned render handler](https://github.com/ollama/ollama/blob/v0.34.3/server/routes.go),
[pinned API fields](https://github.com/ollama/ollama/blob/v0.34.3/api/types.go),
[pinned runner tokenizer](https://github.com/ollama/ollama/blob/v0.34.3/llm/llama_server.go).
These implementation contracts are qualified against the actual pinned binary,
not assumed from a newer server's documentation.

Validation so far: 54 initial request/ownership/readiness regressions passed;
64 token/request/ownership tests passed; the extended native setup/request suite
passed **91 tests**. Ruff F/E9 passed. The first actual diagnostic rejected an
omitted zero-valued `image_count`; the pinned API explicitly omits that field when
zero. Corrected the parser and retained the failed diagnostic report. Classification:
implementation/API mismatch, fixed now. The second actual diagnostic passed all
ten model/lifecycle observations; its prepared input count **113** matched the
runtime's **113** evaluated tokens. The first adversarial real run additionally
matched Unicode (192 tokens), literal control-token/code text (126), and paired
history (126), then hit the existing eight-second GGUF inspection deadline. The
failed report is preserved as `CETA_OFFLINE_TOKENIZER_REAL_20260928.json`.

Diagnosis measured the same header at 0.840 seconds with a plain cancellation
event, versus 5.051 seconds and 46 authority checks with the accumulated synthetic
task journal (checks took 0.084-0.133 seconds each). The 0.1-second authority polling
interval started before a check, so checks lasting longer than that interval
could repeatedly starve parsing. The interval now starts at check completion.
User cancellation remains immediate, revocation still rechecks, and no parser
deadline/size limit was relaxed. A deterministic slow-authority/revocation test
and 69 token/task/role/request regressions passed. Classification: polling
starvation, fixed now. The repaired actual run
`CETA_OFFLINE_TOKENIZER_REAL_FINAL_20260928.json` passed 15 observations: prepared
and evaluated counts matched for Unicode (192), literal control-token/code text
(126), paired history (126), and a long prompt (1106). Oversized mandatory input
was refused with zero generation intents and an idle backend; cancellation and
owned shutdown/reconciliation/restart also passed.

Final review additionally fixed stale generation metrics surviving a preflight
failure and temporary cancellation-event replacement before acquiring a busy
client's operation guard. Added regression coverage; the final focused token/
allocation/coordination run passed 44 tests. The full source gate
`evidence/CETA_OFFLINE_TOKENIZER_20260928.json` passed **660 run, 659 passed,
one environment skip**, zero failures/errors, 196.015 seconds including overhead.
The skip is the temporary volume lacking a distinct Windows short-path alias.
All **230 attributed source files** stayed unchanged, SHA-256
`a5f0f3e392189a424d01b0fb60f1d9d368d4f4d4cd709cc292fb9ba1aba27c22`.
`evidence/CETA_OFFLINE_TOKENIZER_QUALIFIED_20260928.json` also passed all **15**
real-model observations against that same source digest. All four boundary counts
matched the evaluated counts again; oversized input remained rejected before
generation, and both owned stops reported zero active processes. This is source
CETA with actual Qwen3 0.6B and synthetic prompts, not a frozen installer, OS
network-isolation test, GPU qualification or model-quality certification. Earlier
passing reports remain evidence for their recorded source revisions only.

The native counted-request preview was captured and visually checked at 1440x1080
in `evidence/CETA_OFFLINE_TOKENIZER_PREVIEW_FONTS_20260928.png`. The input/output/
context margin and qualification text wrap readably above the composer. This uses
a synthetic model/count fixture. The first offscreen capture lacked glyphs because
Qt's offscreen platform had no loaded Windows fonts; it is retained as a diagnostic.
Registering the installed Segoe UI fonts in the capture process resolved that
environment issue without changing application fonts or source.

Source-package manifest/checksum regeneration and checks passed: 398 payload
files, 399 checksum entries and 400 total registered package files. No commit,
push, new installer, signing or public
release is part of this increment. The full product goal remains incomplete.

## Eleventh increment: protected managed asset sessions (2026-09-28)

Added `managed_assets.py` and integrated it into owned startup/shutdown, native
runtime/model selection, guided setup and exact request tokenization. On Windows,
the session opens each pinned file before hashing with read sharing only. Existing
incompatible writers or writable mappings prevent admission. Files cannot be
written, renamed or deleted through ordinary file operations while protected.
Directory handles protect containing paths against renames, including ancestors
above the CETA data directory; they do not prevent new child entries. Admission
rechecks the runtime tree and rejects unexpected files/directories or unreadable
directories. Reparse points, multiply linked files and changed handle identities
are rejected. Protection is retained until owned workers report zero active
processes. Cancellation/query uncertainty does not release a running job's files.

Verification failures roll back only newly acquired protection. Closing during a
hash is nonblocking and requests cancellation; that operation releases handles
on exit. Model selection protects the pinned manifest and shared blobs. An
uninterrupted session reuses its hash verification while checking file identities;
restart creates a new session and rehashes. Tokenization and generation bind the
job, worker and asset-session identity. Stale/released sessions cannot silently
reuse readiness. Cancelled/stale native callbacks close unadopted sessions.

The first focused run executed 59 tests with ten fixture errors: `unittest.mock`
reserved the `assert_runtime` name as an assertion. An explicit mock method fixed
the fixture. The subsequent affected native/setup/ownership suite passed 90 tests.
Final parent-rename, writable-mapping and unreadable-tree coverage passed with the
tokenizer regressions: 38 tests. Ruff F/E9 passed. These are source tests, not
installed-product qualification.

The first real-model report, `CETA_OFFLINE_ASSET_LIFETIME_REAL_20260928.json`,
stopped because Python's CRT file-open exception did not preserve the Windows
sharing error. No file was written. The harness now checks `CreateFileW` directly
using OPEN_EXISTING and performs no write operation. Classification: verification
harness error, fixed now. The retained diagnostic
`CETA_OFFLINE_ASSET_LIFETIME_REAL_FINAL_20260928.json` passed 19 observations:
88 files denied write access with sharing error 32, real probe/chat and boundary
token counts passed, cancellation/reconciliation/restart passed, and both stops
reported zero active workers and released write access. That report predates the
final containing-directory/inspection changes; final-source evidence is recorded
below.

Final source gate `CETA_OFFLINE_ASSET_LIFETIME_20260928.json`: **681 run, 680
passed, one environment skip**, zero failures/errors, 185.703 seconds including
overhead. The temporary volume lacks a distinct Windows short-path alias. All
232 attributed source files stayed unchanged, SHA-256
`3570fd06617d8da7b19432fbcf784539bd474202be482d8e4b4e2e37b3098a17`.

`CETA_OFFLINE_ASSET_LIFETIME_QUALIFIED_20260928.json` passed all 19 real-model
observations on that exact unchanged final source. The 88 protected files comprise
82 runtime files, five model blobs and the model manifest. Write access was denied
with sharing error 32 in both owned sessions and became available after each
zero-worker stop. Synthetic probe/chat, exact Unicode/control-text/history/long
input counts, oversized input refusal, unload, cancellation and restart passed.
This remains the observed Qwen3 0.6B CPU path, not GPU, quality, frozen-application
or OS network-isolation qualification.

`CETA_OFFLINE_ASSET_LIFETIME_GUIDED_20260928.json` passed the native source
offline-import/probe/close/reopen/recheck journey against the same final source.
Both shutdowns reported zero workers; restart retained the model choice without
readiness. Both probes completed (0.781 and 1.532 seconds, reported VRAM zero).
Only archive dialog inputs were supplied and the download transports were forbidden;
hardware, owned workers and inference were real. The 0.6B model still followed the
requested response format inconsistently, so quality remains unqualified under
W07. The gate tests completed text liveness and lifecycle, not response quality.
All earlier evidence and diagnostic reports are preserved.
Source-package manifest/checksum generation, both check modes and package
verification passed: 405 payload files, 406 checksum entries and 407 total
registered package files. No commit, push, installer or public release occurred.

This sharing boundary does not claim OS isolation, protection against injected
or privileged code, prevention of newly created DLLs, or atomic lock retention
across parent-process death. The latter and wider loader/device qualification
remain explicit W03 follow-up work. Existing advanced/external runtimes do not
inherit managed-session qualification. No personal-project material crossed into
CETA, and these changes do not authorize signing or publication.

## Twelfth increment: shared request deadlines and cancellable inventory (2026-09-28)

Added `request_control.py` with a process-bound monotonic request budget. Native
chat starts its 180-second budget before preparation. The prepared plan carries
the original deadline through preview review and generation; nested scopes cannot
extend it, and changed/foreign receipts are refused. Expired review preserves the
composer. Context gathering, directory traversal, Git inspection, exact tokenization,
hardware checks and local HTTP connect/read/write observe cancellation and the
remaining budget. Provider streaming uses the same deadline. Late monitor callbacks
cannot cancel a reused client after the prior stream has ended.

Timeouts retain their distinct result/status, partial text and retry material.
They do not masquerade as a user Stop action. A timeout after dispatch still leaves
the backend uncertain unless termination was observed; existing owned stop and
reconciliation rules remain in force. The budget is cooperative: native filesystem
or SQLite calls, final evidence writes and shutdown cleanup are not yet proven to
return within a hard latency bound. Arbitrary blocking callbacks are not forcibly
interrupted. These limits remain W04 qualification work.

Hardware inventory accepts cancellation/deadlines and limits its command output.
NVIDIA/PowerShell probes use the existing owned Windows job helper. DXGI runs in a
contained child so a stalled driver query does not pin a Python worker indefinitely.
The child has source and frozen entry points, but only the source child has actual
execution evidence at this stage. Reported DXGI budgets belong to that child, not
the inference worker. RAM-only request admission avoids irrelevant GPU probes.
Guided refresh failure clears stale hardware text and choices. Every observation
comes from the machine executing CETA; no development-host defaults were added.

The affected regression suite passed 205 tests. Additional deadline fault coverage
passed 17 tests, including mid-scan cancellation, stalled connect/write and delayed
monitor behavior. The first full source gate ran 701 tests with one failure, no
errors and one environment skip: an older transport assertion required the literal
phrase `two minutes`, although a shared request can have less time remaining.
Updated that test to assert the specific timeout type, simulated 120-second read
limit and unchanged cancellation event, alongside the new remaining-time message.
Classification: outdated assertion fixed now; 20 focused transport/deadline tests
passed. The failed report is retained as
`evidence/CETA_OFFLINE_REQUEST_DEADLINES_20260928.json`.

Final source gate `evidence/CETA_OFFLINE_REQUEST_DEADLINES_FINAL_20260928.json`
passed: **701 run, 700 passed, one environment skip**, no failures/errors,
188.531 seconds including overhead. The skip is the temporary volume's unavailable
distinct Windows short-path alias. All 234 attributed source files stayed unchanged, SHA-256
`bcb2c8fdf917b3d1f4ceaafe9294d9d2c01736badbb813be81e8a20f621321af`.
Ruff F/E9 and `git diff --check` passed.

`evidence/CETA_OFFLINE_REQUEST_DEADLINES_REAL_20260928.json` passed all **26**
actual-model observations against the same unchanged source. The 30-second shared
budget returned `timed_out` in 30.828 seconds, retained the real partial output
`Here`, kept the caller's cancellation event unset and retained uncertain backend
state until stop/reconciliation. The restarted runtime answered again. Four token
boundary cases matched prepared/evaluated counts; oversized input was refused.
All three shutdowns observed zero active workers. In all three sessions, 88 pinned
files denied write access while active and released it after shutdown. The observed
path reports zero VRAM use. Qwen3 0.6B instruction following remains inconsistent;
no quality, GPU, frozen-app or OS-isolation qualification follows from this pass.

`evidence/CETA_OFFLINE_REQUEST_DEADLINES_GUIDED_20260928.json` passed the native
source offline-import/test/close/reopen/recheck/test/close journey against the same
unchanged source. Both close operations observed zero workers. The saved model
choice survived without live readiness; hardware and assets were checked again.
The actual probes took 1.281 and 1.016 seconds and reported zero VRAM. Download
transports were forbidden; only the archive file-dialog selections were supplied.
The real hardware/process/inference path was not mocked. Inconsistent response
format still prevents a model-quality claim. The frozen helper and installed,
OS-isolated journey remain W09/W10 work.

The real-model harness has an explicit deadline case that delays its output
consumer after receiving actual model text. It checks partial-output retention,
timeout classification, an unchanged cancellation event and stop/reconcile/restart.
This controlled consumer delay is not evidence of an actual backend stall or a
universal hard interruption guarantee. No source test qualifies GPU performance,
model quality, OS network isolation or installed-product readiness by itself.

Source-package manifest/checksum generation, both check modes and package
verification passed: 411 payload files, 412 checksum entries and 413 registered
package files. All diagnostic evidence remains retained. No commit, push, new
installer, signing or public release occurred; the full product goal remains active.

## Thirteenth increment: measured text capabilities (2026-09-28)

Added `capabilities.py` and a native **Measure this configuration** panel. This is
an explicit, disclosed seven-request workload on the selected managed model:
one cold response, two strict instruction checks, one synthetic selected-file
check through the actual attachment path, then three warm samples. The selected
digest must be absent before the cold sample; ambiguous alias residency is refused
instead of silently unloading another tag. OS file caches remain intact. Requests
use the normal TaskRuntime/LocalProvider admission, exact tokenization, authority,
cancellation, deadlines and evidence paths. No separate authority implementation,
downloads, user project content or model-generated executable code is introduced.
Synthetic files are retained under a new uniquely named current-profile directory.

Fixture matching is independent of model assertions. Exact-token and typed JSON
checks reject explanations, wrong values, missing source paths and extra fields.
Quality failures remain specific to that check; they do not become transport
success or stop the other samples. Wall-clock first-visible/total timings and
runtime-reported token counts, decode/load durations are recorded separately.
No character-to-token conversion is used. Missing/invalid/insufficient metrics
leave speed unmeasured. Three warm samples must each have at least 16 reported
output tokens, first text within five seconds and decode rate at least five tokens
per second to receive the narrow synthetic responsive label; otherwise valid
observations are slow. The pinned API duration contract is documented in
[Ollama 0.34.3 types](https://github.com/ollama/ollama/blob/v0.34.3/api/types.go).

Reports bind the source/frozen executable hash, Python/app/fixture version, process
session, hardware observation, managed runtime archive, model profile, protected
asset session, owned worker and 4096-context/1024-output/single-request settings.
Fresh admission still checks available memory per request. The canonical journal
retains measurement intent/result and ordinary governed request evidence. Restart
does not restore a live observation; history is always labelled historical.
Native settings/hardware/worker changes invalidate displayed observations. An
explicit stop retains completed rows without promoting an incomplete suite.

The first 12-test run exposed Windows newline translation in the synthetic fixture;
the fixture now uses an exclusive UTF-8 file with canonical LF bytes. The next
68-test affected native regression run passed 67 and found tuple/list differences
between the returned hardware observation and its journal JSON. Normalized reports
to canonical JSON-compatible data before persistence/return. Classification: both
issues fixed now. All 15 capability tests now pass, including the real governed
attachment path with a synthetic provider, stale/session/worker invalidation,
failed quality outcomes, missing metrics, ambiguous residency and native Stop/history
journeys. Touched-file Ruff F/E9 passes. Actual-model and final source results follow.

The initial actual-model report `CETA_OFFLINE_CAPABILITIES_REAL_20260928.json`
passed 15 execution/lifecycle observations, including the seven-request capability
suite, against source `83863c48e02835bd81ec390ebdbffe14b8695223690508958a9121d8bd4047fa`.
The suite took 182.484 seconds: text completed, both strict instruction fixtures
and the strict selected-file JSON-format fixture failed. Warm first-visible times
were 23.453/23.265/24.047 seconds, while reported decoding was about 41-45 tokens/s.
The fresh synthetic-file project took 3.125 seconds to first text. This identifies
an application latency problem in the accumulated profile; the cause still requires
profiling under W08. It is not evidence that more GPU alone fixes responsiveness.

Review of that retained diagnostic found one unrelated warm answer incorrectly
counted as matched by the original liveness predicate. Tightened warm matching to
the complete requested 1-60 sequence, and speed classification now requires three
matching warm samples. Otherwise timings remain visible but the speed label stays
unmeasured. Also require the synthetic file's observed hash to match the originally
created bytes before attachment admission; changed files are preserved and refused.
Both negative regressions pass. Final focused capability suite: **16 passed**.
Earlier runtime observations remain valid for their recorded source, but its warm
classification is superseded by this explicit correction. Final-source evidence follows.

The subsequent 717-test source gate passed (716 passed, one environment skip) and
the actual native measurement/restart journey passed against unchanged source
`5fa39f8a9c40bfee9a9d08fc8eeb5ce56b31f6b9c3d7f25a9f9450061e843423`.
The fresh profile's suite took 61.672 seconds: text liveness passed, strict
instruction/file-format checks failed, and speed remained unmeasured because one
warm sample did not match. Both closes observed zero workers, and reopening
presented only historical capability records. The source/native reports and the
visually inspected 1440x1080 screenshot are retained under `CETA_OFFLINE_CAPABILITIES`.

Final review added deadline checks after metadata inspection and immediately before
accepting the suite. A late final observation now returns timed out, retaining rows
without current eligibility. The UI explicitly calls 21 minutes a request budget
and discloses inspection/stopping overhead. The new fault regression passes with
the focused suite: **17 passed**. The prior actual native report predates only this
deadline/wording guard; final-source results are recorded after the rerun. Hard
native-I/O/cleanup latency remains W04 qualification work.

Final source gate `CETA_OFFLINE_CAPABILITIES_FINAL_20260928.json` completed with
**718 run: 717 passed, one environment skip, zero failures/errors**, in 212.282
seconds including overhead. The skip is the unavailable distinct Windows short
alias on the temporary volume. All 237 attributed source files stayed unchanged;
source SHA-256 is `1dd55dc6b89565a4c3cf3f0346601865667f0f120755626b81a5a394d0a5ad21`.
`CETA_OFFLINE_CAPABILITIES_GUIDED_FINAL_20260928.json` passed the actual native
offline import, explicit measurement, close/reopen/recheck, historical-only display
and final close against that same source. Both closes observed zero workers; neither
readiness nor a live capability observation was restored from history. The seven
requests completed in 63.844 seconds. Text liveness passed, both strict instruction
checks and selected-file JSON formatting failed, and one unmatched warm answer kept
speed unmeasured. Warm first-visible times were 5.031/6.438/6.109 seconds; reported
decode rates were approximately 41-42 tokens/second. These are CPU-path observations
on this test machine, not transferable GPU qualification. The final 1440x1080 native
screenshot was visually inspected; workload disclosure, controls, failures and
scrollable observed answers are readable. OS network isolation and frozen/installed
application qualification were not performed by this source journey.

Source-package manifest/checksum generation, both check modes and package
verification passed: 421 payload files, 422 checksum entries and 423 registered
package files. No commit, push, installer build, signing or public release occurred.

This implements measured instruction/file smoke and timing observations; it does
not certify general answer quality, reviewed code effects, larger contexts, GPU
placement, vision, voice or autonomous actions. Ranking candidate models using
qualified observations, broader fixtures and installed hardware qualification
remain W07/W09 work. The full product objective remains active.

## Fourteenth increment: repeated journal verification latency (2026-09-28)

The previous real-model run identified long accumulated-profile first-text delays.
Read-only profiling of its synthetic database found 1,839 application events and
22,068 event-hash calculations across three task/events/head read sequences.
Canonical validation/serialization dominated this repeated work. Added bounded
process-local memoization of successful event hashes in `runtime/journal.py`.
Every persisted field and its type must exactly match the stored verified row
before a hash calculation can be reused. Every read still queries SQLite, decodes
fresh payloads and checks sequence, predecessors, project identity, task membership,
head and retained-history constraints. Projections are still checked normally.
No mutable decoded payload is cached or shared with callers, and no timestamp,
trigger, head or database-version shortcut establishes historical integrity.
The cache caps retained entries at 4,096 and conservative row-storage accounting
at 8 MiB. Oversized/evicted records receive full verification; close releases it.

Added seven deterministic regressions covering hash-work reuse with independent
returned payloads, changed persisted fields, cross-connection tampering and valid
appends, projection changes, rollback and both cache limits. The initial 28-test run
exposed a Windows cleanup error in the new tampering test: SQLite's transaction
context does not close its connection. Explicitly closed the connection; classified
fixed now. Expanded journal/task/preparation/authority/replay run: **85 passed** in
21.722 seconds. Touched-file Ruff F/E9 and whitespace checks passed.

`scripts/profile_journal_reads.py` compares disabled/enabled memoization inside one
read-only SQLite snapshot, retaining source attribution and counts without event
payloads. `CETA_OFFLINE_JOURNAL_PROFILE_20260928.json` passed: uncached three-read
total 1.133225 seconds and 22,068 hashes; cache-enabled total 0.478649 seconds and
1,839 hashes, including its cold first iteration. Approximately 58% less elapsed
time for this specific read workload. Retained row accounting was 5,212,313 bytes.
This is not yet an end-to-end model/UI responsiveness claim. Final source and real
model verification results follow after execution.

Full desktop/governed-runtime gate `CETA_OFFLINE_JOURNAL_CACHE_20260928.json`
passed **725 run: 724 passed, one environment skip, zero failures/errors** in
184.219 seconds including overhead. The skip remains the temporary volume's
unavailable distinct Windows short alias. All 238 attributed source files stayed
unchanged at SHA-256 `943fc7244b1e70d17dd9aeaa576e19eacdfac0353f0956e6a4c29b4d7cd33d36`.

The same-source actual model report `CETA_OFFLINE_JOURNAL_CACHE_REAL_20260928.json`
passed 11 execution/lifecycle observations, including generation, seven capability
fixtures, unload, cancellation, reconciliation and restart. Both stops observed zero
workers. The accumulated profile's suite took 122.937 seconds; warm first text was
15.500/15.157/15.641 seconds, versus the earlier 23-24 seconds. History had grown, so
these are observational comparisons rather than a controlled timing ratio. Strict
instruction/file-format failures and unmeasured warm quality/speed remain truthful.
Classification: improved but still unacceptable accumulated-profile response delay.

Follow-up call-site inspection found `_access` repeated task/timeline/grant reads,
each verifying the same entire stream. Added `Journal.task_snapshot` to obtain task
state and filtered events in one verified transaction, and use it for timeline,
access-status and access admission. Existing signature, principal, current time,
revocation and requested-operation checks remain. Every new check obtains a fresh
snapshot; no grant or authority result is cached. Three further deterministic
regressions cover independent snapshot payloads, one stream verification per access,
unsupported operations and revocation from another runtime. Final validation follows.
Expanded journal/task/preparation/authority/replay/roles/recovery suite passed
**107 tests** in 29.819 seconds. Touched-file Ruff F/E9 passed again.

Final source gate `CETA_OFFLINE_JOURNAL_SNAPSHOT_FINAL_20260928.json` passed
**728 run: 727 passed, one environment skip, zero failures/errors** in 173.140
seconds including overhead. The same Windows short-alias skip remains. All 238
attributed source files stayed unchanged at SHA-256
`a07394382bbea6913f0e3e3ba665b0b373ca47fc2f8f3376d0d12a034a5290e2`.

`CETA_OFFLINE_JOURNAL_SNAPSHOT_REAL_20260928.json` passed 11 actual model/lifecycle
observations on that same source. Both stops observed zero workers. The accumulated
profile's seven requests took 90.922 seconds; warm first-visible times were
9.532/9.109/9.156 seconds, compared with 15-16 seconds after cache alone and 23-24
seconds in the original diagnostic. These are observational runs on a growing
profile, not a controlled percentage claim. Decode rates remained approximately
39-41 reported tokens/second. Text liveness passed; strict instruction/file-format
checks failed and one unmatched warm answer kept speed unmeasured.

Read-only timing inspection of the final warm_1 task found context recorded at
3.204 seconds after task creation, prepared request at 6.001 seconds, and provider
intent at 8.225 seconds. The application stream now has 2,415 events. Classification:
the repair reduces latency but does not resolve accumulated-history responsiveness.
Next profiling should measure context compilation, request preparation and final
dispatch admission separately, preserving their validation. Cache storage remains
bounded; larger histories still require full row scans and uncached hash work.

The smaller existing synthetic setup profile also passed 11 real-model/lifecycle
observations on the same final source in
`CETA_OFFLINE_JOURNAL_SNAPSHOT_SMALL_PROFILE_20260928.json`. Its seven-request suite
took 46.281 seconds; warm first-visible times were 3.422/3.766/3.546 seconds. Both
stops observed zero workers. The same strict quality failures remained, so CETA
correctly did not promote the faster timings to a qualified speed capability.
This supports prioritizing history-dependent application work while keeping model
quality repair separate. No GPU execution, frozen installer, OS network isolation,
general quality or complete-product readiness is claimed. The full objective remains
active; no installer build, signing, publication or cross-project transfer occurred.

Final source-package manifest/checksum generation, both check modes and package
verification passed: 428 payload files, 429 checksum entries and 430 registered
package files. No commit or push occurred; previous evidence remains retained.

## Fifteenth increment: ordinary-chat instruction following (2026-09-28)

Inspection of the exact saved request showed that application chat was always
instructed to act as a coding assistant, return explanations/proposed changes and
cite paths, followed by internal task metadata. The real 0.6B model answered a
random exact-token request by describing a file operation that had not occurred.
Classification: the default product prompt conflicts with ordinary chat and strict
response formats; model capability remains a separate limit.

Changed the default prompt to answer everyday questions and coding requests directly,
respect the requested format, avoid unsolicited JSON fences/commentary, disclose
uncertainty and avoid unsupported claims about file/tool actions. Project metadata
and applicable instructions remain mandatory for project contexts; ordinary chat
omits internal application labels/ids from model instructions while retaining them
in governed context and receipts. Selected sources remain data, not instructions.
Application authority, prepared-request identity, source validation, token allocation
and execution gates are unchanged. No prompt branch recognizes benchmark cases.

Added deterministic request tests for plain-chat metadata isolation, unchanged user
messages, retained project/role instructions and payload binding. The focused
allocation/tokenizer/role/capability suite passed 56 tests in 16.696 seconds. Ruff
F/E9 and whitespace checks passed. The actual-model harness gained five independent
arithmetic, conversational recall, sentence rewriting, Unicode-copy and JSON-array
checks. Quality mismatches are recorded, never relabelled as capability success.
The original seven capability fixtures and pass criteria remain unchanged; real
model and final-source results follow after execution.

First diagnostic `CETA_OFFLINE_CHAT_PROMPT_REAL_20260928.json` completed 16
execution/lifecycle observations against unchanged source
`f7b8924e47e5be70c605d3bbef6cab99092f197ab01fae3ad691dff4a62eb2a4`.
The 0.6B model now answered ordinary arithmetic coherently, passed conversation
recall and sentence rewriting, and matched all three warm counting samples. It
still failed strict token/JSON/file-format cases; arithmetic's requested number-only
format and Unicode copying also failed. JSON-specific wording in the default
prompt coincided with unrelated JSON answers, so removed that special wording and
kept the general requested-format instruction. This is a prompt simplification,
not a claimed model-quality fix; diagnostic results remain retained.

Live memory inspection selected the catalog's existing balanced Qwen3 4B Instruct
candidate for CPU admission on this machine. Initiated its pinned asset acquisition
through the governed model.download path into the existing synthetic setup profile.
No user profile selection or hardware defaults were changed. Asset integrity,
actual generation and quality remain separate gates; results follow after execution.

## Scope remaining from the original plan

| Package | Current state and next evidence |
| --- | --- |
| W00 baseline/attribution | Baseline/verifier attribution and installed Ollama 0.34.3 service-health/lifetime checks implemented; full backend/tokenizer/model compatibility and remaining failure reproductions still required. |
| W01 complete request/attachments | Complete request allocation now consumes exact rendered counts on the supported managed path; immutable execution identity and broader backend qualification remain required. |
| W02 renewal/recovery | Implemented surfaces above pass the final source/native gate; later packaged restart/offline acceptance remains required. |
| W03 backend/hardware admission | Selected-executable/device admission, resource plans, unknown-RAM rejection, rendered token counts and protected managed asset sessions implemented. Parent-crash protection, wider loader/tokenizer/runtime qualification and real GPU/load evidence remain required. |
| W04 concurrency/cancellation/switching | Shared leases, owned health/lifetime, job-bound chat/probe, restart/unload and a shared preparation/review/generation deadline implemented. Real Qwen3 0.6B lifecycle evidence is CPU-only. Hard native-I/O/audit/cleanup latency bounds, GPU and frozen-backend qualification remain required. |
| W05 runtime/catalog acquisition | Pinned runtime and six model choices, verified download/resume, offline import/export, native controls and protected session binding implemented. Explicit failed-stage discard/repair and final runtime qualification remain required. |
| W06 guided setup | Chat entry and guided inspect/install/import/test/skip/existing/recheck paths implemented; choices survive restart without readiness. Native fixtures and actual-source offline import/probe/close/reopen/recheck have passed. Cancellable inventory and failed-refresh clearing are implemented. Packaged and qualified-configuration evidence remains required. |
| W07 qualified capabilities | Configuration-bound synthetic instruction/file checks, cold/three-warm timing observations and explicit native measurement/history controls implemented. General quality, reviewed-code fixtures, qualified larger contexts and measured candidate ranking remain required. |
| W08 archive/search/responsiveness | Repeated event-hash work reduced with exact-row memoization and unchanged integrity checks. Real generation latency qualification, restore/search archives and moving slow project reads off the UI thread remain. |
| W09 installed offline/hardware lane | Pending: exact frozen bytes and real model under documented OS isolation; synthetic tests are insufficient. |
| W10 candidate/lifecycle qualification | Pending after the above product work. |
| W11 signing/public delivery | Pending exact candidate qualification and actual release/publisher authorization; no credentials used. |
| WT training dependency advisory | Separate follow-up within the original scope; fresh advisory/dependency audit and repair still required. |

The next product-facing work is W07 measured candidate comparison and wider
file/coding quality fixtures, plus W08 responsiveness/archive/search. Current
instruction/file smoke observations do not substitute for those gates. W03
parent-crash/loader protection and W04 hard-latency qualification remain required.
Use the native guided-setup and real-model harnesses with the existing tests. Every
package and the final installed/offline/hardware gates remain part of the objective;
passing this increment does not mark that objective complete.
