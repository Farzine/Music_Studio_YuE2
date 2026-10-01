# YuE2 Music Studio — implementation context

Updated: 2026-10-01. Analysis baseline: `2af5461` (`feat: Implement model downloads feature with Hugging Face integration`).

## Current task and handoff

**Phases 1, 2A–2C, 3A–3B, 4A–4B and 5A–5C are complete.** Shared registry/validation/deletion and atomic measured HF downloads preserve legacy paths and requests. The worker owns lifecycle, native Load/Unload, GPU switching/rollback, validation/VRAM checks and graceful shutdown with cancellation settlement, child reaping and explicit cleanup outcomes. Phases 6–9 remain pending; the full enhancement definition of done has not been achieved.

On `Continue from CONTEXT.md`:

1. Check the current diff and preserve any subsequent user changes. Reuse this map; read the files for the next slice and their callers before editing.
2. Start **Phase 6A: Installed Models UI**. Read `apps/web/components/app-shell.tsx`, Settings page/model-downloads/model-selector components, existing UI cards/dialogs, API/query/types and `/models` registry inspect/validate/deletion-preview/delete/load/unload plus `/system/runtime` endpoints together. Add a cohesive installed-model area/navigation and reuse existing inventory/domain facts and worker acknowledgements. Provide Inspect/Use/Load/Unload/Delete with exact model/space confirmation and API blockers; preserve real metadata and separate downloaded/validated/registered/inference-ready/currently loaded states. Adapt Settings links instead of maintaining two inventories. Native VAE selection and task/path-browser UX follow in 6C; repository/recommendation presentation follows in 6B. Preserve asynchronous GPU/shutdown ownership and the explicit GGUF/vLLM persistent-load limits; frontend remains display/UI state only.
3. Complete one slice, run its relevant checks, and update this document with files changed, results, and remaining work before starting the next slice.
4. Keep the API free of PyTorch/CUDA model loading. Runtime operations belong to the worker and its existing manager/adapters.

No user decision currently blocks Phase 6A. Current implementation and validation limits follow; earlier phase findings are historical snapshots where explicitly marked.

## Phase 5C implementation

- Preserved the uncommitted Phase 5B work present at turn start. Read worker main/job/command cleanup, queue/Store admission, session journal, manager and native/audio.cpp/transcription/Comfy/mock adapters, API lifespan/dependencies, download BackgroundTasks/run leases, launchers and their tests. Reused the existing command journal, settings, atomic Store and process/file leases. No dependency, supervisor, second queue or API-side CUDA import added.
- Added priority session-bound `shutdown` requests to RuntimeCommands. Signals and API shutdown reuse the same request; it is idempotent even after acknowledgement, preventing an exit race from leaving a second queued stop. Shutdown can coexist with one in-progress Load/switch, blocks new runtime/generation admission under queue lock and cannot be claimed as an ordinary load. Worker heartbeat/main loop detect it, publish stopping, set cancellation and start no further inference. ModelService/SystemInfo/GenerationService call the same shared admission rule; invalid/old/stopped workers retain existing actionable restrictions.
- Worker startup/finalization now sit inside guaranteed cleanup. Shutdown independently attempts adapter references, retained per-job CLI cleanup, backend shutdown, manager release, job settlement, pending command acknowledgements and final stopped heartbeat; one failure cannot skip subsequent steps. Heartbeats add accepting_work, shutdown.status/errors and shutdown_commands capability. Cleanup failures exit with WORKER_SHUTDOWN_FAILED and stay visible in the System UI; model UNLOAD_FAILED specifically preserves uncertain GPU release. Stop-request and heartbeat persistence are attempted independently. Disk/logging failure can still prevent durable reporting; it is logged and never establishes a false release guarantee.
- Added narrow worker-adapter `settled_call`/`settled_await` helpers: cancellation signals the existing event but waits for the running thread/child startup to finish before dropping model/file references. Repeated task cancellation cannot detach native CUDA work. Native loading/planning/semantic/synthesis/decode/transcription/file checks and worker runtime/queue calls use this seam. SIGINT/SIGTERM continue using existing safe boundaries; uninterruptible load/decode completes before cleanup. A normal active Load/switch settles before stop; task-interrupted commands retain actual result/error snapshots.
- Job cleanup resets runtime use/current job/device/cancel fields even if reporting/backend cleanup fails. The cancellation watcher is signalled done; queued generations are preserved. Under the exclusive worker process lease, startup marks abandoned active generations failed/cancelled with timestamps and does not replay them, preventing stale active jobs from wedging claims. Shutdown terminalizes any owned claim left before execution. Pending Load/Unload/switch records fail with CANCELLED; already acknowledged records stay historical. Offline queuing after completed stop remains backward compatible.
- audio.cpp retains child/communication handles through failure, launches its own session, terminates the process group, waits, escalates to KILL and reaps before clearing external runtime activity. Startup, cancellation, communication error and per-job shutdown use the same cleanup; the worker retains a failed per-job backend for shutdown retry. Transcription now uses equivalent process-session cleanup in finally for timeout/cancel/callback/startup failures; stdout/stderr are drained concurrently, with bounded stderr line history, to avoid pipe deadlock. Native/vLLM model/VAE/cache verification remains manager-owned. POSIX descendant groups are signalled; hard kills, unresponsive drivers and escaped descendants cannot promise cleanup.
- API lifespan cleanup requests shutdown of the configured online (or locally known-alive stale/stopping) updated worker and waits for acknowledgement without importing its runtime. Added WORKER_SHUTDOWN_ON_API_EXIT (default true) and WORKER_SHUTDOWN_TIMEOUT_SECONDS (default 60; zero requests without waiting). Timeout/old worker is logged as unacknowledged/unsupported, never unloaded. `scripts/dev_api.sh --reload` defaults coupling off so development hot reload keeps the separately launched worker alive; an explicitly exported setting wins. `make stop` continues to signal both processes; independently deployed APIs can disable coupling explicitly.
- Normal ASGI BackgroundTasks finish before lifespan cleanup. Download shutdown bookkeeping fails only this API's abandoned active/queued requests when their run lease is free, preserving staging for retry. Live transfers and other owners are untouched; existing atomic publication/dead-owner recovery remains authoritative. No new download cancellation architecture introduced.
- README, settings example, API/architecture/model/troubleshooting docs and System shutdown error/status presentation updated. Broader model-management UI is still Phase 6.

### Phase 5C changed files

```text
packages/core/yue2_studio_core/{runtime_commands,settings,errors}.py
services/yue2_worker/worker.py
services/yue2_worker/adapters/{base,yue2_native,audiocpp,transcription}.py
services/api/app/main.py; services/api/app/services/{generations,models,system_info,model_downloads}.py
scripts/dev_api.sh; .env.example
apps/web/app/system/page.tsx; apps/web/types/api.ts
tests/unit/test_shutdown.py (new); tests/unit/test_model_downloads.py
tests/integration/test_runtime_api.py; tests/conftest.py
README.md; docs/{api,architecture,model-setup,troubleshooting}.md; CONTEXT.md
```

### Phase 5C validation and remaining limits

- Full API-environment unit/integration suite: **412 passed, 2 skipped, 1 unchanged failure** (missing root `yue2_full.json`, parameter-mapping reference test), 70.22 seconds. No new regression failure or fabricated reference file. Focused shutdown/download/worker/runtime API suite: **51 passed**. Final shutdown/command/runtime API recheck after idempotence/error taxonomy/lifespan adjustments: **33 passed**, including the actual lifespan hook and stopped admission. One existing Starlette/AnyIO deprecation warning.
- Worker-environment manager/lifecycle/GPU switch/worker/audio.cpp/shutdown suite: **61 passed**. Native models/devices mocked; fixture children only sleep/write tiny CPU reports. Coverage includes SIGTERM callback installation, active inference cancellation, repeated cancellation during blocking load, pending-command outcomes, cleanup-step failures with stopped/error heartbeat, reporting failure state reset, interrupted-generation recovery, transcription cancel/timeout/callback/full stderr pipe, audio.cpp task/cooperative cancellation/reap, admission and API cleanup acknowledgement, plus prior switch/manager regressions. No GPU needed for normal CI.
- ESLint, production build, sequential TypeScript, Python compileall, dev launcher shell syntax and whitespace checks passed. Browser interaction/responsive coverage remains Phase 7; build/type checks do not prove it. Final stopped/error presentation uses worker facts; no frontend lifecycle decisions added.
- No production server/worker stop/restart, production inference/model movement/deletion/download, registry migration or physical GPU/VRAM shutdown test performed. Real GPU release/shutdown and two-GPU rollback smoke remain pending for a suitable idle hardware window. Hard OS termination, unresponsive CUDA, escaped child groups or filesystem failure cannot guarantee Python cleanup/reporting. Remote Comfy GPU residency remains owned by its remote server; local worker shutdown cannot claim to unload that remote runtime.
- API coupling stops the configured worker on normal server exit; operators relaunch it with the API. Hot reload through the dev launcher deliberately keeps it running, while make stop/signals clean it explicitly. Uninterruptible model calls may exceed the API wait deadline; the request remains pending and logged rather than falsely acknowledged. Old workers need an update/restart to advertise shutdown support. Download threads still finish via normal ASGI semantics; forced termination uses staging recovery.
- Next: **Phase 6A**. No user information currently required. Phases 6–9 and the full enhancement definition of done remain pending.

## Phase 5B implementation

Historical snapshot; shutdown hardening subsequently completed in 5C.

- Started from a clean working tree. Traced `/system/device`, SystemInfo GPU authority, Store settings/queue locks, worker session commands and loop, model/VAE residency/file leases, native/audio.cpp/transcription placement, frontend polling and all related tests. Inspected the pinned native runtime's close, vLLM process wait and CUDA graph cleanup. Extended existing services/adapters and atomic JSON records; no dependency, second queue or API/core inference import added.
- RuntimeCommand adds `select_device`, optional model identity only for that operation, protected rollback references and worker-written stage snapshots. Existing Load/Unload records remain valid; their registry/reference requirements remain enforced. The same pending-command guard blocks new generation claims and concurrent runtime commands. Pending switch references protect deletion, and a manager-held shared lease pins actual model/VAE files throughout release/reload/rollback even if the heartbeat's admission snapshot was old.
- PUT `/api/v1/system/device` now returns **202**, preserving the GPU inventory shape and adding `switch_command`. It validates reported CUDA indices and requires the configured online worker/session with `select_device_commands`. It never writes the selected index on admission. Legacy/old worker GPU facts remain readable, but old workers cannot acknowledge a coordinated switch (409, update/restart once). GET `/system/gpus` exposes latest switch status, stage/error and matching-session freshness; GET `/models/runtime-commands/{id}` retains exact-request readback.
- Worker executes the switch between generations through ModelManager; the active generation settles before control work and a second queued job cannot bypass it. Adapter secondary pipeline references are cleared first. Manager retains the resolved model/VAE/configuration, validates target CUDA availability, closes old resources, checks model/VAE/vLLM references and child exit, collects objects, synchronizes the old CUDA device, clears caches/IPC, and checks zero allocated/reserved bytes in the worker torch allocator before target loading. Other applications/driver contexts are outside this check. Cleanup failure preserves UNLOAD_FAILED evidence/leases and blocks target allocation.
- Target native torch load repeats existing validation/precision/VRAM guards and materializes weights; the selected device is committed under queue lock only after preparation succeeds. Target load or settings-write failure releases target resources before restoring previous selection/model/configuration. Error details expose `rollback_succeeded` / `rollback_error`; failed target cleanup blocks old-device allocation, and failed old reload leaves a clean LOAD_FAILED state with previous selection. An unloaded worker switches without loading an arbitrary default model. Native VAE remains lazy; pinned vLLM prepares a new lazy wrapper and reports deferred generation loading, and audio.cpp has no persistent model to reload.
- GenerationContext now carries the worker's captured job index to native acquire and cover transcription; audio.cpp already captured its CLI index. Transcription child CUDA_VISIBLE_DEVICES maps the worker's logical index through the parent's numeric/UUID visibility list, preventing masked/reordered GPUs from selecting a different physical card. No model/VAE selector semantics changed in this phase.
- GPU selector polls authoritative switch status every second while pending, displays queued/unloading/released/loading/ready/rollback stages and exact errors, disables controls until acknowledgement, and refreshes capability/schema/recommendation/system caches afterward. Reused the installed Radix RadioGroup for keyboard navigation/focus and existing cards/notices; no frontend hardware/model decision rules. Broader Models/task/path-browser UI remains Phase 6.

### Phase 5B changed files

```text
packages/core/yue2_studio_core/runtime_commands.py
services/api/app/api/v1/system.py; services/api/app/services/{models,system_info}.py
services/yue2_worker/model_manager/manager.py; services/yue2_worker/worker.py
services/yue2_worker/adapters/{base,yue2_native,transcription}.py
apps/web/components/settings/gpu-selector.tsx; apps/web/{hooks/use-queries,types/api}.ts
tests/conftest.py; tests/unit/test_gpu_switch.py (new)
tests/unit/{test_model_lifecycle,test_model_validation,test_worker_commands}.py
tests/integration/{test_api_flow,test_hardware_api,test_runtime_api}.py
README.md; docs/{api,architecture,model-setup,troubleshooting}.md; CONTEXT.md
```

### Phase 5B validation and remaining limits

- Focused lifecycle/command/switch/runtime/hardware API suite: **48 passed** before the final additional vLLM case. Final full API-environment unit suite: **291 passed, 2 skipped, 1 unchanged failure** (missing root `yue2_full.json` in parameter-mapping reference test). The combined unit/integration regression run passed all integration cases; its other failure was an older CUDA mock missing synchronize/allocator counters, fixed and verified in the final full unit run. No fabricated reference workflow.
- Final worker-environment manager/lifecycle/switch/command/audio.cpp suite: **47 passed**, including lazy vLLM wrapper reporting. Tests cover release-before-target allocation, pinned rollback files, config/VAE preservation, CUDA allocator counters, active inference ordering, native/transcription device freezing, CUDA visibility mapping, target load/OOM/settings failure, unavailable GPU, unload failure, uncertain target cleanup, rollback-load failure, unloaded/same-device requests, API admission/acknowledgement, deletion protection and exact failure readback. All new cases use fake devices/pipelines or tiny fixture files/CLI; no real GPU required.
- ESLint, final production build (including Radix selector), sequential TypeScript and diff whitespace checks passed. Browser interaction/responsive tests remain Phase 7; builds/types do not prove those behaviors.
- No production weights/downloads/deletion/migration, physical GPU switch/inference or running worker/server restart performed. Managed release checks are implemented and mock verified; a physical two-GPU smoke window is still needed to prove real residency/allocator behavior. vLLM/audio.cpp tensor residency is unknown; zero parent allocator bytes does not measure child/global NVML memory, though normal child exit is checked. Hard OS termination cannot guarantee Python cleanup.
- Shutdown admission/cancellation/finalization nesting, exceptional CLI/transcription process cleanup, stopped-state persistence after cleanup failure and queued commands/downloads at stop remain **Phase 5C**. Direct out-of-band runtime-settings edits preserve legacy idle release behavior; API switching now commits through the worker. Existing session recovery fails interrupted commands without replay.
- Next: **Phase 5C**. No user information currently required. Phases 6–9 and the full enhancement definition of done remain pending.

## Phase 5A implementation

Historical snapshot; coordinated switching and managed release checks subsequently completed in 5B. Shutdown hardening remains 5C.

- Read manager/worker/native/mock/Comfy/audio.cpp callers, queue/Store locks, registry/validation/readiness rules, API dependencies/routes, existing tests and the installed pinned YuE2 implementation before editing. Preserved uncommitted Phase 4B changes present at turn start. Reused filesystem JSON/locks and the existing worker loop/adapters; no broker, dependency or API/core inference import added.
- Added core `model_lifecycle.py` vocabulary and `runtime_commands.py` validated persistent requests/acknowledgements under DATA_DIR/worker-commands. Commands carry target worker/session, explicit registry model/reference, GenerationConfig, frozen device index, queued/running/succeeded/failed status, timestamps and result/error. One pending command per worker is the documented scheduling ceiling. Existing queue lock serializes admission/deletion and blocks new generation claims while control work is pending.
- Extended existing ModelService and model routes: POST `/models/{registry_id}/load`, POST `/{registry_id}/unload` return 202; GET `/models/runtime-commands/{command_id}` returns acknowledgement plus matching-session online status. GET `/system/runtime` exposes authoritative heartbeat/freshness and configured selected index separately. Model registry ID sets checkpoint; VAE paths/sentinels/registry IDs remain independent. API does no CUDA/torch loading. Load/unload targets an online updated native worker; old/stopped/mock/remote Comfy workers are rejected explicitly.
- Each Worker invocation publishes a new session and holds an exclusive worker-ID process lease. Restart recovery fails old queued/running commands without replay, preserving historical outcomes. The serial loop waits for active inference, claims commands before jobs, executes through manager in threads, records result/error and refreshes heartbeat. Pending model/VAE references protect deletion. Queueing alone never claims Loaded; result snapshots are historical, runtime heartbeat is latest. A wrong-model unload fails while preserving the actual resident pipeline.
- ModelManager publishes UNLOADED/LOADING/LOADED/IN_USE/IDLE/UNLOADING/LOAD_FAILED/UNLOAD_FAILED. Atomic snapshots avoid the operation lock so blocking load/close cannot freeze heartbeat/version reads. Native jobs mark use/end-use; idle timeout cannot release in-use or failed-cleanup resources. Idle/device-change mutations moved from heartbeat task into the serial worker loop to remove a load/unload race. Cleanup failures remain visible/usable and require explicit unload retry.
- Unload closes the pipeline, clears owned references, collects objects, clears CUDA caches and releases model/VAE file leases. Close failures preserve uncertain pipeline references; cache failures preserve key/lease evidence. Both report MODEL_UNLOAD_FAILED, mark residency uncertain and block another load until explicit release succeeds. Cleanup failure no longer silently becomes UNLOADED. Strong physical CUDA release verification/rollback and shutdown nesting remain 5B/5C.
- Added public registry `describe(reference, role)` to apply known validation reports/fingerprints without inventory scanning/writes. Direct worker paths, GGUF preflight and resident native reuse now honor stale/failed/incompatible reports and declared native VAE latent compatibility. Legacy unregistered/no-report installations keep their existing file checks rather than forcing redownload/migration. Structural validation remains separate from successful runtime loading.
- Worker-side native load checks current CUDA visibility/device, precision eligibility and the existing core capacity/assessment engine before allocation. Known estimated peak exceeding configured safe VRAM raises actionable CUDA_OOM with estimate/excess details; unknown facts are not guarantees. Failed loads release leases/caches where possible and persist LOAD_FAILED, while failed cleanup retains blockers.
- **Pinned runtime finding:** `YuE2Pipeline.from_pretrained()` resolves files/constructs a lazy pipeline, leaving `_model`/`_vae` unset. Native torch/torch-eager loading now calls the pinned `_load_model()` seam before reporting materialized weights. VAE remains lazy until decoding. Sampling still travels with each request and pipeline keys remain unchanged except explicit command device override. The pinned vLLM child starts during generation and lacks preload; API/worker reject vLLM explicit Load rather than reporting a false load. Existing vLLM generation dispatch remains available.
- Native snapshots expose pipeline readiness, retained resources and representative model/VAE tensor devices/GPU flags separately. During native inference, state reads current tensor placement because decode/offload can move weights to CPU. SystemInfo GPU residency respects those flags and device index; retained CPU weights are not claimed as GPU loaded. Legacy heartbeat compatibility remains. Exact per-model memory is not inferred from allocator totals, and vLLM child placement stays unknown without a runtime probe.
- audio.cpp reports active per-job PID/device with IN_USE, residency_mode=per_job and unknown tensor residency, clearing activity after child exit. Its CLI still has no resident preload session; explicit GGUF Load is unsupported with task-selection guidance. Native resources are released before GGUF execution, and the worker enforces cached validation before the CLI. No standalone GGUF VAE support is invented.
- Existing System card now shows lifecycle, retained/unknown resources, model/VAE placement, CLI PID, active command and cleanup errors from worker facts. Updated optional heartbeat types; dedicated buttons/dialogs/model pages remain Phase 6. Updated README and architecture/API/model docs, including stale model-capacity wording. No frontend model/hardware business rules added.

### Phase 5A changed files

```text
packages/core/yue2_studio_core/{model_lifecycle,runtime_commands}.py (new)
packages/core/yue2_studio_core/{model_registry,store,errors}.py
services/yue2_worker/model_manager/manager.py
services/yue2_worker/worker.py; services/yue2_worker/adapters/audiocpp.py
services/api/app/services/{models,system_info}.py
services/api/app/api/v1/{models,system}.py
apps/web/app/system/page.tsx; apps/web/types/api.ts
tests/conftest.py
tests/unit/{test_model_lifecycle,test_runtime_commands,test_worker_commands}.py (new)
tests/unit/{test_model_validation,test_audiocpp_backend,test_hardware}.py
tests/integration/test_runtime_api.py (new)
README.md; docs/{api,architecture,model-setup}.md; CONTEXT.md
```

### Phase 5A validation and remaining limits

- Full API-environment unit suite: **272 passed, 2 skipped, 1 unchanged failure** (`test_parameter_mapping.py::test_workflow_mapping_matches_the_reference_workflow`, absent root `yue2_full.json`). The first broad run also exposed an older fake-loader test lacking its configured local VAE; added a real tiny VAE fixture and reran. No production weights used for new runtime tests; no fabricated workflow file.
- Full integration suite before the final additional GGUF/vLLM preload case: **101 passed**. Final affected runtime/worker/model-action/hardware API suite: **35 passed**, including that additional case. Final lifecycle/command/worker/hardware/validation/runtime-API check after idle/failure guards: **75 passed**. One unchanged Starlette/AnyIO deprecation warning.
- Final worker-environment manager/lifecycle/command/audio.cpp regression suite: **28 passed**. Final targeted command/heartbeat recheck: **6 passed**, including target GPU reporting during LOADING before tensors exist. Tests cover blocking state reads, load/reuse/use/idle/unload, cached/stale validation, VAE mismatch, real pinned factory materialization seam, CPU placement, precision/margin/no-GPU preflight, failed loading/close/cache cleanup, protected leases, malformed records, session recovery, duplicate-worker rejection, active inference ordering, acknowledgements and actual fixture CLI process activity. All use fake pipelines/devices or tiny fixture CLI/files; normal CI needs no GPU or installed YuE2 for new lifecycle tests.
- Confirmed sandbox thread-callback stall: bounded verbose readiness run exited 124 with executor idle and asyncio selector waiting. Worker-environment async tests likewise timed out in sandbox; the same suites passed outside sandbox. TestClient limitation was already documented. Escalated test runs used only temporary data/mocks, no production changes.
- ESLint, Next production build, final sequential TypeScript and diff whitespace: **passed**. No browser interaction runner yet; lifecycle card behavior is build/type verified, browser/responsive action tests remain Phase 7. No new dependency, downloads, model file movement/deletion, GPU inference/switch, production worker restart or production registry migration performed.
- Native priming/placement uses the inspected pinned private `_load_model`, `_model`, `_vae`, `_vllm_worker` seams; contract tests must accompany runtime upgrades. Tensor device inspection is representative, not a complete multi-device tensor/memory census. vLLM/audio.cpp child tensor placement is unknown, and allocator bytes remain process-wide. VAE materializes only during decode and is typically moved back to CPU by the runtime.
- `/system/device` still writes legacy selection immediately; idle cleanup/next acquire releases an old native key, but it does not yet coordinate full release verification, target preload, selection commit and rollback. A load command freezes the accepted index. Native generation/transcription still need coherent job-device freezing in 5B. Old/new residency is observable; no stronger physical release claim was tested.
- Graceful shutdown cleanup/acknowledgement nesting, rejecting admission while stopping, cancellation/finish policy, exceptional CLI cleanup and pending commands/downloads at stop remain 5C. Live queued commands await the worker; if it stops before execution, restart recovery fails them rather than replay. No command-cancel route added. Old heartbeats without sessions must come from an updated worker before control commands; ordinary legacy generation/settings behavior remains available.
- Installed Models Load/Unload/Delete dialogs and task Model/VAE/GPU controls, native VAE HF-role registration and Settings path browser remain Phase 6; browser/coverage consolidation (7), remaining docs/final validation (8–9) remain pending. Full enhancement definition of done is not complete.
- Next: **Phase 5B**. No user information currently required. Physical switch/release/rollback smoke requires suitable idle hardware later; mock tests cannot prove physical VRAM release.

## Phase 4B implementation

Historical snapshot; explicit worker lifecycle/commands and validation-report enforcement subsequently completed in 5A.

- Read the existing downloader, HF helper, registry/validator/file leases, API and Settings caller, pinned SDK transfer paths and tests before changing code. Reused SDK 0.36.2, two-second polling, BackgroundTasks, Store atomic JSON/file locks, structural readers and registry descriptors. No dependency, separate transfer architecture or API/core tensor loading added.
- Added shared core `model_download.py` for valid queued/downloading/verifying/registering/complete/failed transitions, byte accounting and the existing 1 GiB disk reserve. Unknown selected totals produce null percentages/ETA; failure/retry transitions are explicit. Download completion and inference readiness remain separate.
- Added narrow `huggingface_transfer.py`: ContextVar-scoped callbacks through the pinned SDK private progress factory, preserving HTTP resume, Xet, auth, cache and unrelated SDK progress bars. Actual logical file-byte callbacks drive progress; Xet preallocation is not polled as progress. The private seam has real SDK HTTP/Xet contract tests with mocked transport and must be checked on SDK upgrades.
- Extended preview/start to all three modes, immutable commit and exact selected files. Default companion selections retain legacy destination identity; different content selections add a deterministic identity suffix so new repository content cannot overwrite an existing smaller installation. Remote local-control paths are rejected. Disk checks use the nearest existing destination parent under MODELS_DIR/hub, account for observed existing requested content pending verification, and repeat before transfer/when unknown SDK totals resolve.
- Reworked existing ModelDownloads around private same-filesystem `MODELS_DIR/hub/.downloads/<job_id>` staging, absent final destinations until admission, symlink/path guards, cross-process admission lock and per-job execution lease. One active download is an explicit throughput ceiling. Existing task/residency destination leases remain authoritative; no worker content is overwritten.
- Every selected file receives size/SHA256 checks, with expected Hub LFS SHA256 comparison when provided; known GGUF/safetensors files receive structural checks. Shared package validation determines completeness/compatibility independently. Corruption fails without registry admission; missing sidecars and unsupported encodings/families remain explicit unavailable/unvalidated states. Quantized native MLX configuration is detected through both quantization_config and quantization. Declared parameter counts use the same positive-integer constraints as remote metadata.
- Added `ModelRegistry.install_verified`: lock inventory, publish stage by same-filesystem directory rename, persist fingerprinted validation report and register the shared validated descriptor. Publication/registration failures restore newly published content to private staging. Existing identical destinations require matching source identity and full selected-content verification, and are never silently overwritten. Atomic Store JSON/rename remains process-interruption protection, not stronger power-loss durability.
- Persisted schema v2 download jobs include exact files, progress, nullable rate/ETA, attempt, validation/inference outcome and registry ID. New POST retry returns 202; DELETE partial cleanup removes only failed jobs' private staging. Existing POST/default requests and `complete` status remain compatible. Retry pins new jobs to the same commit/selection and forces bad staged files past SDK cache. Legacy jobs remain readable; failed legacy retries resolve their old revision once and preserve installed paths.
- Recovery distinguishes dead/recycled local PIDs from live/remote owners. A v2 running job with a free execution lease becomes interrupted even if the API process lives; live transfer leases are preserved. Live queued jobs await BackgroundTasks and are not falsely interrupted. Damaged persisted jobs fail explicitly rather than permitting unsafe concurrent downloads. Allocated staging blocks (`partial_bytes`) are distinct from logical progress bytes.
- Existing Settings panel now offers single-package, selected-file and full-repository content; accessible file checkboxes, preview invalidation, overall/file native progress bars, bytes/percent/speed/ETA, phases, errors, attempt count, Retry and Remove partial files. Tanstack Query remains the server cache; frontend performs no model/hardware business decisions. Dedicated navigation/pages/actions and browser test tooling remain 6/7.

### Phase 4B changed files

```text
packages/core/yue2_studio_core/model_download.py (new)
packages/core/yue2_studio_core/{model_metadata,model_registry,model_validator}.py
services/api/app/services/huggingface_transfer.py (new)
services/api/app/services/{huggingface,model_downloads}.py
services/api/app/api/v1/models.py
apps/web/components/settings/model-downloads.tsx
apps/web/{lib/api.ts,types/api.ts}
tests/conftest.py; tests/unit/test_model_downloads.py
tests/unit/test_huggingface_transfer.py (new)
tests/integration/test_model_downloads_api.py (new)
README.md; docs/{api,huggingface-models}.md; CONTEXT.md
```

### Phase 4B validation and remaining limits

- Full unit suite: **248 passed, 2 skipped, 1 unchanged failure** (`tests/unit/test_parameter_mapping.py::test_workflow_mapping_matches_the_reference_workflow`, missing root `yue2_full.json`). Final full run includes unknown-size/recovery cases and last storage/accounting guards. Do not invent that reference workflow.
- Full integration suite: **98 passed**, one unchanged Starlette/AnyIO deprecation warning. Outside sandbox due to documented TestClient portal stall; temporary fixture files and mocked HF/GPU. Focused download/HF/registry/structural checks before final reserve/accounting tightening: **95 passed**. Worker model manager under `.venv-yue2`: **9 passed**.
- New tests cover real tiny native/GGUF packages, single/selected/repository API transfers, pinned retry, hidden staging, size/hash/structural failures, publication rollback, leases/concurrent admission, orphan/live-owner recovery, interrupted cleanup, disk failures, symlink preservation, unknown sizes and preserving old installations. Pinned SDK tests exercise actual HTTP resume/ignored Range and Xet progress paths with mocked responses, concurrent ContextVar scopes, unrelated SDK fallback and exception reset.
- ESLint, Next production build and final sequential TypeScript: **passed**. Diff whitespace checks: **passed**. No frontend browser runner yet; responsive/interaction assertions remain Phase 7. Avoid concurrent build/typecheck because Next regenerates `.next/types`.
- Live **README-only** SDK download smoke outside network sandbox: `audio-cpp/Yue2-3B-GGUF` at `eb14a51700bf8baac825a690b2f3b24a01239f85`, 9,986 bytes, two callbacks, final reported count matched actual completed file size; HTTP total stayed unknown. Temporary directory cleaned automatically. No weights downloaded, physical GPU inference/switch, worker restart, production registry migration or model deletion performed.
- Speed is sampled logical file-byte processing, not network-interface throughput; cache hits have no invented speed. Unknown sizes, other processes and SDK caches outside destination storage can still exhaust space. Preview/free-space checks are point-in-time; failures retain staging. SDK partial cache/resume is reused, not replaced by a custom HTTP downloader. One active download and sequential file validation are the current throughput ceilings.
- Whole-repository content registers only its explicit primary model; alternate weights are stored but not independently selectable registry entries. Different content identities can duplicate shared weight storage. Arbitrary shards/architectures/encodings are manageable downloads, not new runtime support.
- Native VAE HF download role propagation/legacy role migration remains pending for **6C**: the current primary download registers role=model, while the Settings primary browser excludes identified decoders. Existing configured/local VAE import and default workflows remain supported. Standalone GGUF VAE choice still depends on the pinned audio.cpp runtime; its current adapter uses bundled F16.
- New private partial cleanup never deletes legacy unregistered directories or installed content. Existing corrupt destinations require explicit Inspect/Delete; they are preserved. Queued jobs with a live API owner still await the background task; cancellation/graceful API download coordination belongs later lifecycle work. Hard OS termination cannot guarantee Python cleanup or power-loss durability.
- Worker-owned load/unload/lifecycle commands (5A), dynamic switching/rollback (5B), shutdown (5C), dedicated model/task/file-browser UX (6), browser/coverage consolidation (7), remaining docs/final validation (8–9) remain pending. Full enhancement definition of done is not complete.
- Next: **Phase 5A**. No user input currently required.

## Phase 4A implementation

Historical snapshot; atomic selected/repository transfers, measured progress and recovery subsequently completed in 4B.

- Read the complete downloader and its routes/Settings caller, shared metadata/readiness/estimation, SDK 0.36.2 signatures/objects and related tests before editing. Reused existing HfApi, polling, Settings models directory, shared descriptors, atomic JSON job persistence, package layout and registry seams. No new dependency or inference import in the API/core.
- Added focused `services/api/app/services/huggingface.py`: validated repository/revision/file inputs; immutable commits; repository/card metadata, branches/tags, all files/nullable sizes/LFS SHA256; bounded streamed configuration JSON; adapter candidates; deterministic quantized-lineage discovery with per-repository errors. Tokens/raw upstream exception URLs are not echoed to clients.
- Missing/invalid metadata remains Unknown; only explicit positive integer parameter counts are accepted. Filename quantization/precision hints are labelled unverified and kept separate from actual facts. Remote Python is never executed and no model weights are read during inspection. Repository description/license can be null when structured card data omits them.
- Shared `model_metadata.py` now owns native companions, required files, layout/configuration checks and declared VAE latent-width comparison. Local inventory and remote inspection reuse these rules. Missing-file messages retain priority; empty/unreadable bundled VAE metadata cannot become a positive compatibility claim. This exposes unsupported pre-quantized native safetensors explicitly rather than claiming the current loader supports them.
- Added internal remote-config/bundled-VAE inputs to existing memory/assessment and SystemInfoService. Actual remote context dimensions and VAE bytes refine the same estimates; no second recommendation engine. Native candidate/selected installed VAE latent widths are compared. Candidate IDs cannot become runnable, loaded or task-selected through an estimate.
- Added `POST /models/hub/inspect`, `POST /models/hub/preview`, `GET /models/hub/discover` above dynamic ID routes; all have `/api/v1` prefix. API composes candidate assessments with existing installed decoder/runtime inventory, returns selected/all-GPU explanations, and strips internal configuration contexts. Existing `/models/hub` response and download request/job/polling contracts are retained.
- Single/selected/repository preview modes validate every path/file, deduplicate selection, preserve primary identity and commit, list missing sidecars, distinguish known byte totals/lower bounds and inspect the nearest existing MODELS_DIR parent filesystem. No preview installation/registry write. Known totals + 1 GiB exceeding free space prohibit download; unknown sizes remain explicit. File-as-directory storage configuration fails with a useful error.
- Reused a shared destination/default-related-files helper in the existing transfer runner, keeping its exact hash/directory identity and legacy package behavior. Actual selected/repository transfers, checksum admission, atomic staging and measured byte/rate/ETA progress are 4B.
- Extended existing Settings download panel: inspect, revision suggestions, select primary model, preview content/storage/metadata/GPU reasons and start at the pinned commit. Source/file changes invalidate previews; busy controls prevent stale response selection; identified VAE artifacts are excluded from the primary model browser. Quantized repository discovery is read-only and never downloads automatically. Full dedicated pages and browser coverage remain Phase 6/7.

### Phase 4A changed files

```text
services/api/app/services/huggingface.py (new)
services/api/app/services/{model_downloads,system_info}.py
services/api/app/api/v1/models.py
packages/core/yue2_studio_core/{model_metadata,model_recommendations}.py
apps/web/components/settings/model-downloads.tsx
apps/web/{lib/api.ts,types/api.ts}
tests/conftest.py
tests/unit/test_huggingface.py (new)
tests/unit/test_model_recommendations.py
tests/integration/test_huggingface_api.py (new)
docs/huggingface-models.md (new)
README.md; docs/{api,model-recommendations}.md; CONTEXT.md
```

### Phase 4A validation and remaining limits

- Full unit suite: **225 passed, 2 skipped, 1 unchanged failure** (`tests/unit/test_parameter_mapping.py` expects absent root `yue2_full.json`). Focused final HF/download/readiness/recommendation/structural-validation checks: **108 passed**. Covers unsafe paths, revisions, exact/unknown metadata, hints, pinned/bounded JSON streams, disk volumes/unknown sizes/insufficient storage, selection modes, missing sidecars, partial discovery errors and remote/native VAE mismatch.
- Full integration suite: **93 passed**, one unchanged Starlette/AnyIO deprecation warning; affected HF/readiness/recommendation recheck: **10 passed** after metadata/storage tightening. Tests ran outside sandbox due to documented TestClient stall, using fixtures and temporary files. Worker model manager: **9 passed**.
- ESLint, production Next build, final TypeScript and diff whitespace checks: **passed**. An initial concurrently launched typecheck raced Next's generated `.next/types` removal; reran typecheck sequentially after the successful build and it passed. Run build/typecheck sequentially in future.
- Live **metadata-only** smoke outside network sandbox: example repository resolved `eb14a51700bf8baac825a690b2f3b24a01239f85`, 34 files, main ref, four main GGUF variants and two decoder files, no inspection warnings. Quantized-lineage discovery (limit 3) inspected `ahmadw/YuE2-3B-MLX`, `audio-cpp/Yue2-3B-GGUF`, `scragnog/YuE2-GGUF`, no repository errors. These are dated changing observations, not a shipped static list or compatibility guarantee. No model weights downloaded, GPU load, device switch, worker restart, deletion or production registry migration performed.
- Candidate compatibility is declared configuration/layout evidence; actual tensor architecture/quantization/content requires post-download validation. Unsupported model families/MLX/native shard layouts acquire no runtime here. Standalone GGUF VAE selection is not promised; the existing audio.cpp adapter still uses its bundled F16 decoder.
- Discovery is bounded/sequential (1–20 repos). SDK metadata/ref/catalog behavior is retained; optional metadata failures expose warnings. No custom cache, parallel crawler or background architecture added. Preview free space is a point-in-time check; transfer must recheck. Unknown totals cannot guarantee capacity. All-repository mode can include large alternate weights/examples and must retain a clear preview.
- Current downloads still have legacy file-count progress and non-atomic whole-package installation; 4A adds previews only for selected/repository content. Existing file leases protect active tasks from writes, but staging/atomic admission, byte progress, verification/recovery/retry remain **Phase 4B**. No frontend/browser test runner is configured yet.
- Worker lifecycle/GPU switching/shutdown (5), dedicated model pages/actions/task selectors/file browser and broader UX (6), frontend/coverage consolidation (7), remaining docs and final validation (8–9) remain pending. Full enhancement definition of done is not complete.
- Next: **Phase 4B**. No user input currently needed.

## Phase 3B implementation

Historical snapshot; HF candidate inspection/discovery subsequently completed in 4A.

- Added shared core `model_recommendations.py`: per-GPU capacity envelopes, model/VAE/cache/runtime estimates, deterministic explainable capability states and sorting. No tensor loading, new dependencies, frontend business rules or extra model registry.
- Removed the fixed three-file benchmark list from SystemInfoService. Existing `/system/model-recommendation` now assesses actual inventory models on every worker GPU; `items` selects the requested/current GPU and `by_gpu` covers every GPU. Legacy `variants` projects those assessments, `recommended` remains nullable, `max_model_bytes` becomes comfortable heuristic capacity and `max_parameters` is null rather than a fabricated universal count.
- Capacity reserves the greater of a configurable total-VRAM fraction and fixed GiB margin, plus configured VAE/cache/runtime workspace. Conservative, comfortable and upper file-size envelopes and hypothetical Q4/Q5/Q8/BF16 parameter capacities are labelled heuristic. Installed parameter counts remain nullable metadata facts.
- Estimates expand weights (default factor 1.25), include native FP32 VAE/bundled GGUF VAE sizes, runtime workspace and BF16 KV cache. Extracted `budget.kv_cache_bytes_per_token` reuses the existing formula; model config supplies full context/two CFG branches when available, otherwise a configured cache reserve. Conservative peak adds weight headroom. Native BF16 parameter metadata supplies a lower bound, never a filename-derived count.
- Idle cached manager-owned PyTorch reserved memory is conditionally reclaimable after unload/cache release, capped at physically used memory. Busy job allocations, other process memory, CUDA contexts and audio.cpp subprocesses are not counted as reclaimable. A currently reported model in active inference remains unknown for incremental headroom instead of being falsely marked unable to run from duplicate load costs.
- Native allocator cap is scenario budget minus the installed runtime's 2 GiB reserve. Shared prerequisites, structural validation, declared model/VAE latent-width matching, BF16 eligibility, CLI/native runtime availability, GPU utilization and host loading/offload RAM influence status. AR offload does not discount full-load requirements; vLLM placement/cache remains unknown instead of borrowing a torch guarantee. Unsupported/missing/corrupt/deleting states remain blocked.
- Query options on the existing recommendation endpoint: device_index, vae, offload_ar, compute_backend and budget_gib. Explicit missing devices/invalid scenarios return 422; metadata ranges and finite coefficient/query constraints prevent unsafe arithmetic. Candidate descriptors use the same core engine but uninstalled candidates are never runnable; HF discovery is not implemented yet.
- Replaced the old GPU-0/coefficient task VRAM warning with a projection of the same model estimate. Create now passes its actual model/VAE/offload/compute selection. Full waveform decoding explicitly needs unprofiled extra memory; warning estimates do not alter task settings or admission.
- System page now shows per-GPU capacity, hypothetical parameters, installed recommendations/status/reasons and expandable memory components. Actual model parameter counts display Unknown unless supplied. GPU selection refreshes schema/capability caches as well as hardware/recommendations. Task model/VAE/GPU dedicated controls and model action UI remain Phase 6.
- Added six validated estimate settings to Settings/.env.example, API/TS contracts, README/API documentation and `docs/model-recommendations.md` with coefficients, statuses, troubleshooting and backend extension guidance.

### Phase 3B changed files

```text
packages/core/yue2_studio_core/model_recommendations.py (new)
packages/core/yue2_studio_core/{budget,settings}.py
services/api/app/services/system_info.py
services/api/app/api/v1/system.py
apps/web/{app/system/page.tsx,features/create/create-form.tsx,hooks/use-queries.ts,lib/api.ts,types/api.ts}
tests/unit/test_model_recommendations.py (new)
tests/unit/{test_hardware,test_model_downloads}.py
tests/integration/test_recommendations_api.py (new)
.env.example; README.md; docs/api.md; docs/model-recommendations.md (new); CONTEXT.md
```

### Phase 3B validation and remaining limits

- Full API integration suite: **91 passed**, unchanged Starlette/AnyIO deprecation warning. Final recommendation/hardware API recheck after metadata/query guards: **7 passed**. TestClient requires execution outside sandbox; temporary files and mocked hardware/inference only.
- Final full unit suite: **196 passed, 2 skipped, 1 unchanged failure** (`tests/unit/test_parameter_mapping.py::test_workflow_mapping_matches_the_reference_workflow`, missing root `yue2_full.json`). Do not fabricate that reference file. Focused recommendation/hardware/download/token-budget check: **76 passed**; worker model-manager environment: **9 passed**.
- TypeScript, ESLint, Next production build and diff whitespace checks: **passed**. No real GPU load/inference, real HF download, production registry migration/deletion, new dependencies or worker restart performed. No browser test runner is configured yet; interactive/keyboard coverage remains Phase 7.
- The daemon restart interrupted finishing docs/context, not implementation. Recovered edits were checked before resuming; final checks above completed and the phase is ready for handoff. No commits were made.
- These are estimates, not measured peaks. Full-context/two-CFG/tiled-decoding assumptions and conservative summed model/VAE costs can overestimate actual native stage peaks; missing cache/VAE costs can be inaccurate. Coefficients and reserves are visible/configurable. No performance/quality ranking from file sizes or invented parameter counts.
- Host RAM is not container limits or remote worker RAM. Native loading/offload RAM factor is heuristic; vLLM, full waveform decode, and alternative backends need measured profiles. Current native manager reports cached pipeline identity rather than complete tensor-level GPU residency; Ready/currently_loaded follows that worker report, not a new physical-residency proof. Precise residency (including GGUF CLI), lifecycle and switch/unload verification remain Phase 5.
- Capacity's quantization rows are hypothetical storage envelopes, not blanket quantization/backend support. Shared validation/preflight still governs actual known variants; native shards/additional GGUF block encodings remain limited as documented in 2C. Validation does not verify numerical tensor values or full semantic layer coverage.
- HF candidate inspection/discovery (4A), atomic/measured downloads (4B), worker lifecycle/GPU switch/shutdown (5), dedicated model actions/task selectors/file browser and broad UX (6), browser/coverage/docs/overall validation (7–9) remain pending. The full enhancement definition of done is not complete.
- Next: Phase 4A. No information is currently required from the user.

## Phase 3A implementation

Historical snapshot; general estimates and model recommendation UI were subsequently added in 3B.

- Added shared core `hardware.py` for host CPU/RAM facts and native arithmetic eligibility. Linux MemAvailable includes reclaimable cache; total-RAM fallback uses stdlib sysconf and leaves available/used RAM unknown. No new dependencies or torch import in the API/core.
- NVML scan now returns UUID/PCI identity, per-device driver, nullable memory/precision/utilization/process facts. Unsupported sensors or unavailable device handles preserve other devices/facts. Unknown process memory is not fabricated as zero.
- Worker snapshots report actual CUDA_VISIBLE_DEVICES, UUID, per-device allocated/reserved bytes and precision provenance. Native BF16 is checked with `torch.cuda.is_bf16_supported(including_emulation=False)` inside each device context; older runtimes retain labelled hardware eligibility. Invalid selected indices and partial device-probe failures are observable without losing healthy GPUs.
- SystemInfoService merges logical worker GPUs with physical cards only by UUID, never matching names/indices. Live matched NVML memory supersedes older heartbeat memory; `memory_source`/timestamps distinguish the sources. API settings no longer stand in for the worker's visibility mask. Unknown identity suppresses unsafe merging.
- Fresh stopped/failed, expired/future/malformed heartbeat records and known dead same-host PIDs are offline. New heartbeats identify hostname; legacy/remote workers use heartbeat freshness because API cannot prove their process liveness. Malformed non-object hardware/runtime/model records are skipped.
- An online worker's view is authoritative even when it reports zero CUDA devices. Offline physical cards are informational/nonselectable and CUDA availability is unknown. `/system/device` rejects unconfirmed CUDA indices, including empty inventories. Existing frozen runtime choice is preserved until a valid selection succeeds.
- FP8 capability and VRAM warnings use the selected worker CUDA index, not physical GPU 0. Manager-reported resident device takes precedence over changed idle selection for heartbeat placement. `loaded_model` uses online manager state; allocator counters are explicitly not exact model-only memory or audio.cpp subprocess usage.
- Existing System/GPU UI displays CPU/RAM and per-GPU runtime, driver, identity, precision, residency and allocator facts. Offline stale model state is not shown as currently loaded. Benchmark recommendation labels now say estimated fit/headroom instead of verified/runnable.
- General model capacity, reserves and recommendation rules were not implemented in this facts slice. Existing benchmark logic remains a backwards-compatible limited estimate; unknown selected/free memory yields no recommendation. Storage still reports DATA_DIR's disk, not a future selected download destination.

### Phase 3A changed files

```text
packages/core/yue2_studio_core/hardware.py (new)
services/api/app/services/{system_info,capabilities}.py
services/api/app/api/v1/system.py
services/yue2_worker/worker.py
apps/web/{types/api.ts,app/system/page.tsx,components/settings/gpu-selector.tsx}
tests/unit/test_hardware.py (new)
tests/integration/test_hardware_api.py (new)
tests/integration/test_api_flow.py
README.md; docs/api.md; CONTEXT.md
```

### Phase 3A validation and remaining limits

- Full integration suite: **87 passed**, one unchanged Starlette/AnyIO deprecation warning. Final hardware/selection API recheck after last changes: **4 passed**. Outside sandbox due to documented TestClient stall; temporary files/mock inference only.
- Final hardware/download/readiness unit check: **34 passed**, including reordered identical GPUs, selected precision, unknown identity/memory, stopped/dead/malformed workers, RAM fallback, partial NVML/worker probes and no-GPU paths. Worker model-manager environment: **9 passed**.
- Full unit run before the final additional malformed-worker case: **161 passed, 2 skipped, 1 unchanged failure** (`yue2_full.json` missing). Added case passed in the focused recheck. Do not fabricate the missing reference workflow.
- TypeScript, ESLint and production Next build: **passed**. Diff whitespace check: **passed**. No real GPU inference, worker restart, new dependency, downloads/deletion or production state migration performed.
- RAM reports host memory, not cgroup constraints. UUID-less legacy workers cannot merge live statistics until restarted; no index/name guess is made. BF16 query is runtime eligibility without emulated allocation; FP16 and FP8 are hardware/runtime thresholds, not tested kernels/model loading. NVIDIA primary documentation linked in README; installed PyTorch and YuE2 source inspected for version-specific behavior.
- Worker/manager is still only partially lifecycle-aware; GGUF CLI residency, explicit load/unload commands, coordinated switching/rollback and shutdown hardening are Phase 5. Per-task GPU control, separate dedicated Model/VAE dropdowns and keyboard/browser coverage remain Phase 6/7.
- Next: Phase 3B. No information is currently required from the user.

## Phase 2C implementation

- Added core `model_validator.py`: bounded safetensors and little-endian GGUF v2/v3 readers, tensor shape/range/alignment/overlap/truncation checks, duplicate-key detection, architecture/VAE/config checks and optional weight SHA-256 verification against available manifests. No tensor loading, torch imports or new dependencies. Unknown formats/encodings remain unvalidated and block availability after validation.
- Existing `model_metadata.py` owns bounded JSON metadata reading, model/VAE sentinel resolution and native declared latent-width compatibility. Selected safetensors filenames are identified honestly; unsupported native layouts report a blocker rather than checking a different file. Native config model_type and GGUF sidecar model/VAE architecture govern preflight compatibility; removed GGUF filename-prefix inference restrictions.
- Read-only smoke checks of existing weights found audio.cpp GGUF main/VAE headers declare `general.architecture=audiocpp`; the main also declares `audiocpp.model_spec.family=yue2`. Validator supports this actual package, and both native installations plus the local GGUF package passed structural validation without modifying files/production registry or loading a GPU.
- Observed precision, GGUF tensor quantization and stored `tensor_element_count` are available. Tensor elements are deliberately not presented as exact parameters. Parameter counts remain null unless explicitly declared by config metadata. Computed hashes are distinct from matching trusted/provided expected hashes; `checksum_verified` requires expectations for all checked weights.
- Validation reports persist separately under `DATA_DIR/model-validations`, with device/inode/size/mtime/ctime/required-file fingerprints. Inventory applies them only while fingerprints match. Changed complete files require revalidation, stale observed counts/precision/hashes are hidden, and failed/corrupt reports disable submission. Runtime availability remains a separate live check.
- Added focused API ModelService and routes: GET `/models/{registry_id}`, POST `/{registry_id}/validate`, GET `/{registry_id}/deletion-preview`, DELETE `/{registry_id}` (all `/api/v1/models`). Registry IDs now address actions; frozen task checkpoints still use paths/sentinels.
- Deletion requires both exact `confirmed_path` and the preview's file-snapshot token. It refuses unfinished task model/VAE references, leases, older live-worker loaded heartbeats, unreadable safety records, overlapping installations, external locations, mounted files/directories and protected application data/config/runtime roots. File tables show exact content, partial files and approximate allocated bytes reclaimed; symlink targets and shared hard links are preserved.
- Deletion journals `deletion_status=deleting` and a validated hidden sibling staging path before renaming the directory on the same filesystem. Registry removal follows successful cleanup. Failed/interrupted cleanup remains unavailable and can be retried with a fresh preview. Hidden deletion staging directories are excluded from inventory migration. Existing Store atomic writes are reused; this is process-interruption recovery, not stronger power-loss/database durability.
- Core `model_files.py` provides sorted per-canonical-directory shared/exclusive advisory leases using Store.file_lock. Native manager pins model/VAE files across residency, releasing leases on normal unload/failed loading; Worker pins files during each job (including GGUF); downloader takes an exclusive destination lease; validation uses shared leases; deletion fails promptly on exclusive conflicts. API never loads/unloads models.
- Generation admission validates and enqueues under the existing queue lock, preventing a delete between validation and enqueue. Delete lock order is queue → file leases → registry. Native VAE availability/declared latent width is checked independently; native manager reuses shared file/architecture prerequisites.
- API types, README, model/API docs and offline fixtures/tests updated. Dedicated action buttons/confirmation dialogs remain in Phase 6; do not claim new UI pages shipped in 2C.

### Phase 2C changed files

```text
packages/core/yue2_studio_core/{model_validator,model_files}.py (new)
packages/core/yue2_studio_core/{model_metadata,model_registry,store}.py
services/api/app/services/models.py (new)
services/api/app/services/{generations,model_downloads}.py
services/api/app/api/v1/models.py
services/api/app/core/deps.py
services/yue2_worker/{worker,model_manager/manager}.py
apps/web/types/api.ts
tests/unit/test_model_validation.py (new; 29 tests)
tests/integration/test_model_actions_api.py (new; 5 tests)
tests/conftest.py
tests/unit/{test_model_registry,test_model_readiness,test_model_downloads}.py
tests/integration/test_model_readiness_api.py
README.md; docs/{model-setup,api}.md; CONTEXT.md
```

### Phase 2C validation and remaining limits

- Full integration suite: **84 passed** in 60.63 seconds. Final model-action/readiness API recheck after subsequent safety edits: **9 passed**. Runs outside sandbox due to documented TestClient stall; temporary models/mock inference only. Existing Starlette/AnyIO deprecation warning.
- Final full unit suite: **144 passed, 2 skipped, 1 unchanged failure** (`yue2_full.json` missing). New validator/deletion suite covers 29 cases including corruption, checksums, expired results, architecture, file leases, shared files, task/VAE protection, failed cleanup/retry, failed load/unload lease cleanup and concurrent admission/deletion. Earlier combined focused suite: 56 passed; subsequent focused cache/readiness regressions: 51 passed before the last worker architecture test was added.
- Worker environment model-manager suite: **9 passed**. TypeScript, ESLint and diff whitespace checks: **passed**. No production build repeated for API/core/type-only changes; Phase 2A build passed.
- Read-only real-weight structural smoke: native model **validated/supported**, native VAE **validated/supported**, GGUF package **validated/supported**. No real inference, full weight hashing, download, production registry migration or deletion performed.
- Native root `model.safetensors` remains the supported layout; native shard integration still pending even though the installed native library supports shards. GGUF structural block sizes currently cover F32/F16/BF16, Q4_0/Q4_1, Q5_0/Q5_1 and Q8_0/Q8_1; new block encodings must extend the reader explicitly. Structural checks do not verify tensor numerical values or semantic layer coverage and cannot guarantee runtime/GPU compatibility.
- Whole-repository download staging, measured byte progress, hardware memory estimates, robust load/unload/failure lifecycle and device switching, shutdown hardening and frontend model actions remain pending. Downloader discovery can still expose incomplete directories; its exclusive lease keeps the worker from reading during a studio transfer, but complete atomic staging/admission is for Phase 4B.
- File leases coordinate studio processes and require updated workers; external manual edits do not respect them. Old live-worker residency is guarded conservatively by heartbeat. External installations cannot be deleted via this managed-root API. Disk-space reclamation is approximate; model report hashing is synchronous and explicit.
- No user information is required for the next hardware-facts slice.

## Phase 2B implementation

Historical notes; inspect/validation/deletion and action IDs were added subsequently in 2C.

- Added shared `model_registry.py`, using Store's atomic JSON writer and extracted `file_lock`. The queue still locks its original `.queue.lock`; registry writes use a separate `.model-registry.lock`. No new dependencies or API routes.
- `DATA_DIR/model-registry.json` has a validated version-1 document and installation records. Persistent `ModelFacts` are shared with live descriptors; runtime/readiness, loaded state, defaults and file-validation results are not stored as registry authority.
- Existing configured native/VAE directories, recognized siblings and `models/hub` packages import on inventory scans. Successful downloads register immediately after all requested files and installation metadata are written, before their job completes. A failed transfer does not register its partial files through the download-completion path.
- Canonical directory plus model/VAE role determines a stable `registry_id`; absolute symlink aliases deduplicate. Inventory/task `id` values still use legacy paths. Registry IDs are informational, not checkpoint inputs in this slice. Worker reference handling and frozen project/job configs are unchanged. Moving a directory creates a different installation identity.
- Imports are idempotent: unchanged records retain timestamps and cause no registry rewrite. `created_at` is first import/registration, not a recovered legacy download date. Changed facts/aliases update `updated_at`. Known repository/revision/size metadata is retained when files disappear; availability is checked live on every inventory request.
- Missing GGUF installation metadata cannot cause a registered GGUF package to be reported as native-ready. Removed/retargeted aliases are not accepted by API resolution as the old installation. A full hexadecimal revision is recorded as `commit_hash`; branches/tags and unknown parameter counts remain nullable, and a later branch revision clears a previously known commit hash.
- Corrupt/invalid/newer registry documents yield actionable `INVALID_CONFIG` errors and are never silently replaced. Restore a backup, or preserve the damaged file under another name before explicitly rebuilding through an inventory scan. Rebuild restores deterministic IDs for the same discovered paths, but not original import dates, undiscoverable aliases or external registrations absent from scan roots.
- API model types and model/API documentation cover these semantics. Existing readiness test fixtures now explicitly isolate registry writes in temporary data directories.

### Phase 2B changed files

```text
packages/core/yue2_studio_core/model_registry.py (new)
packages/core/yue2_studio_core/{model_metadata,store}.py
services/api/app/services/{capabilities,model_downloads}.py
services/api/app/core/deps.py
apps/web/types/api.ts
tests/unit/test_model_registry.py (new)
tests/unit/{test_model_downloads,test_model_readiness}.py
tests/integration/test_model_readiness_api.py
docs/{model-setup,api}.md
CONTEXT.md
```

### Phase 2B validation and remaining limits

- Focused registry/readiness/download/audio.cpp checks: **29 passed**. Subsequent alias/commit-clearing regression checks: registry suite **11 passed**.
- Full API integration suite: **79 passed** in 60.03 seconds, including persistent inventory/live runtime updates and registry corruption/recovery. Ran outside the sandbox because the documented TestClient startup stall remains; tests use temporary data/mock inference. One existing Starlette/AnyIO deprecation warning.
- Full unit suite: **115 passed, 2 skipped, 1 unchanged failure** (`yue2_full.json` missing). Worker-environment model manager: **9 passed**.
- TypeScript and ESLint: **passed**. Diff whitespace check: **passed**. Production build passed in Phase 2A; not repeated for this registry/type-only slice.
- No real downloads/GPU inference, weight movement, user registry migration on the production data directory or new runtime dependencies. Registry recovery/concurrent writes tested with temporary files and mock downloads.
- Content/header/checksum validation, generic native filenames/shards, deletion, hardware capacity, HF repository modes/measured byte progress, worker lifecycle, independent task controls and new pages remain pending. Registry scanning retains the existing YuE2 discovery rules; registered does not mean validated or loaded. The existing downloader is not yet atomic for whole installations: a recognized incomplete native directory may be discovered during transfer, but its live required-file status governs availability. Address staging/admission in 4B.

## Phase 2A implementation

Historical implementation notes; registry persistence below was completed subsequently in Phase 2B.

- Added `packages/core/yue2_studio_core/model_metadata.py`: typed installation descriptors, shared model-reference/metadata helpers, existing adapter file checks, GGUF companions and executable availability. No torch/CUDA imports. Unknown parameter count/architecture/precision/quantization remain null.
- Descriptors expose download/file/validation/registration/compatibility/inference states. `inference_ready` and legacy `present` are derived from one inference status. Downloaded weights stay downloaded when the CLI is absent. `validation_status=not_validated`, `registration_status=discovered` and `currently_loaded=null` honestly describe the current limits.
- Capability inventory uses those descriptors; default/explicit model resolution uses the same inventory and CLI checks. Schema assembly preserves pre-disabled options instead of enabling them again.
- Generation validation gates `inference_ready`, distinguishes runtime incompatibility (`UNSUPPORTED_CAPABILITY`, HTTP 409) from missing files, and rejects VAE entries as model checkpoints. Health uses the same preflight descriptors rather than directory existence alone.
- Worker dispatch resolves `default` before GGUF detection. Audio.cpp uses the resolved directory during validation, command creation and manifest hashing, while keeping the original requested config unchanged. Native manager and API budgeting reuse the same checkpoint resolver.
- Download and Settings UI separates Downloaded from Available for inference and shows exact blockers, pending inventory checks and check failures. Create uses the backend schema to block unavailable model submission and detect default GGUF options.
- Added readiness/metadata/API regression tests and default-vs-explicit fake-CLI coverage. Replaced a flaky progress test's 20 ms polling with observation of successful Store writes: the old watcher sometimes missed the real, brief POST_PROCESSING stage. Application stage timing is unchanged.
- Documentation updated in README, `docs/model-setup.md` and `docs/api.md`.

### Phase 2A limits and next work

This is preflight availability using the existing adapter file requirements, not content/header/checksum validation, GPU load validation or hardware estimation. Native runtime probing, architecture detection, generic file layouts and independent GGUF VAEs remain for later slices. Existing YuE2 filename/sidecar rules are isolated in the shared module; additional formats are not yet supported for inference.

Registry persistence/migration (2B), content validation/deletion (2C), lifecycle transitions and authoritative residency (5A) are not implemented. A downloaded installation is `discovered`, not falsely labelled as a durable registry record. Presets/reset still replace explicit model/VAE settings; preserving selections and dedicated Model/VAE/GPU controls remain in 6C. Frontend validation here is type/lint/build plus API contract tests; interactive browser tests remain pending.

Modified files in Phase 2A:

```text
packages/core/yue2_studio_core/model_metadata.py (new)
packages/core/yue2_studio_core/parameters.py
services/api/app/services/{capabilities,generations,budget,model_downloads}.py
services/api/app/api/v1/health.py
services/yue2_worker/model_manager/manager.py
services/yue2_worker/worker.py
services/yue2_worker/adapters/audiocpp.py
apps/web/types/api.ts
apps/web/app/settings/page.tsx
apps/web/components/settings/model-downloads.tsx
apps/web/features/create/create-form.tsx
tests/unit/test_model_readiness.py (new)
tests/unit/test_audiocpp_backend.py
tests/integration/test_model_readiness_api.py (new)
tests/integration/test_worker_flow.py
README.md; docs/model-setup.md; docs/api.md; CONTEXT.md
```

Phase 2A validation:

- Focused readiness/download/audio.cpp tests: **17 passed**, including default GGUF dispatch and invalid metadata/path containment.
- Full unit suite: **103 passed, 2 skipped, 1 unchanged failure** (`yue2_full.json` missing).
- Worker environment model-manager suite: **9 passed**.
- Full integration suite after correcting the test expectation and replacing polling in the progress test: **77 passed** in 59.79 seconds. New API readiness tests plus the earlier targeted recheck also passed (**3 tests**).
- TypeScript, ESLint, Python compilation and production Next build: **passed**. `next lint` and Starlette/AnyIO emit existing deprecation notices.
- No real GPU inference or weight download performed; optional audio.cpp remains unavailable locally.

## Repository map and responsibilities

The application uses three processes and a shared filesystem, with an optional transcription subprocess. There is no database or message broker.

| Area | Files / directories | Responsibility and dependencies |
|---|---|---|
| Frontend | `apps/web/app/`, `features/`, `components/` | Next.js 15 App Router, React 19, TypeScript, Tailwind 4, Radix UI. Existing pages: Dashboard, Create, Library, Projects, project settings/history, generations, Scores, Settings, System, About. |
| Browser API / cache | `apps/web/lib/api.ts`, `types/api.ts`, `hooks/use-queries.ts`, `hooks/use-generation-stream.ts`, `app/providers.tsx`, `next.config.ts` | REST through same-origin Next rewrites; TanStack Query caches server state. Generation SSE with polling fallback. Downloads already poll every 2 seconds; System/GPU every 5 seconds. Zustand holds player and dialog targets, not model residency. |
| Design system | `apps/web/components/ui/`, `app/globals.css`, `components/app-shell.tsx` | Shared buttons, cards, fields, selects, dialogs, confirmation dialogs, sheets, help, notices, skeletons and responsive navigation. Keep overlay hosts above list items to preserve the existing body-lock fix. |
| API composition | `services/api/app/main.py`, `core/deps.py`, `core/errors.py`, `api/v1/router.py` | FastAPI; cached service providers; stable error envelope. Separate `.venv-api`, intentionally without torch. `/api/v1` route convention. |
| API services | `services/api/app/services/{capabilities,model_downloads,system_info,generations,projects,budget}.py` | Inventory/capabilities, HF downloads, hardware, validation, persistent project/job bookkeeping, and shared token-budget calculations. Routes remain thin. |
| Shared domain | `packages/core/yue2_studio_core/{models,model_metadata,model_registry,parameters,settings,errors,constants}.py` | Request/project/job types; persistent installation facts and model registry; live file descriptors; config merging/validation; defaults, presets and parameter schema; Settings; error taxonomy. |
| Shared persistence / queue | `packages/core/yue2_studio_core/{store,queue,ids}.py` | Atomic JSON/text writes, path containment, filesystem job queue with advisory `flock`, cooperative cancellation and runtime settings. Reuse these mechanisms. |
| Other shared logic | `packages/core/yue2_studio_core/{budget,tokenizer,manifest,abc,delivery}.py`, `vendor/` | Token/context budgeting; checkpoint tokenizer; reproducibility hashes/manifests; vendored ABC parser; audio download conversion and cleanup. Preserve these flows. |
| Worker | `services/yue2_worker/worker.py`, `jobs/reporter.py`, `engine/artifacts.py` | Claims jobs sequentially, selects adapters, drives stages/cancellation, writes real progress/artifacts/manifests and heartbeats. Dedicated `.venv-yue2`. |
| Model manager | `services/yue2_worker/model_manager/manager.py` | Owns persistent native pipeline, model/VAE resolution, load/reuse/unload, placement, idle release and weight identity. Uses an `RLock`; no explicit lifecycle enum yet. |
| Inference adapters | `services/yue2_worker/adapters/{base,yue2_native,audiocpp,mock,comfy_workflow}.py` | Existing stage protocol. Native YuE2 pipeline; GGUF through one audio.cpp subprocess per job; mock backend; external ComfyUI compatibility backend. Extend these seams. |
| Cover transcription | `services/yue2_worker/adapters/transcription.py`, `services/sheetsage2_worker/transcribe.py` | Separate subprocess/environment because SheetSage2 and YuE2 torch/transformers pins conflict. Cancellation/timeout terminate the child. |
| Declarative config | `configs/{parameter-registry,yue2.defaults,yue2.capabilities,model-limits,presets,workflow-mapping}.json` | Parameter schema/help, request defaults, backend declarations, token-limit fallbacks, presets, and generated ComfyUI reference mapping. |
| Operations | `Makefile`, `.env.example`, `scripts/` | Environment setup, native model download, optional audio.cpp build, process start/stop, GPU smoke test, workflow mapping and version backfill. |
| Tests | `tests/unit/`, `tests/integration/`, `tests/conftest.py`, `tests/fixtures/` | Domain/queue/budget/config/download/adapter tests; API, project lifecycle and mock worker integration. Fixtures isolate `DATA_DIR` and configure the mock backend. No frontend test runner presently configured. |
| Documentation | `README.md`, `docs/` | Architecture, Linux setup, models, API, parameters, covers, scores, licensing, troubleshooting. Update these incrementally with implemented features. |

Analysis covered application source, routes, shared domain/persistence, adapters, configuration, setup/maintenance scripts, existing tests and documentation. Generated dependency trees, virtual environments, binary tools/model weights, Git internals and private environment values are not application source; dependency manifests and model installation metadata were inspected instead. No secrets were recorded here.

### Important installed dependencies

- API: FastAPI 0.120.4, Pydantic 2.12.4, pydantic-settings 2.13.0, huggingface-hub 0.36.2, httpx 0.28.1, nvidia-ml-py 13.580.82, sse-starlette, soundfile, tiktoken. Reuse the installed HF client.
- Worker: torch 2.10.0 with cu126, yue2-infer 0.1.6, transformers 4.57.6, safetensors, numpy, accelerate, soundfile.
- Optional audio.cpp setup pins `0xShug0/audio.cpp` v0.8.2 and builds `audiocpp_cli` with CUDA. Actual CLI option/runtime compatibility still needs testing.
- Settings loads `.env` into cached Pydantic settings, rather than exporting its contents into worker process environment. Device changes are persisted separately and read dynamically.

## Execution paths

### Configuration and inference

```text
Create / project configuration / regenerate
  -> frontend effective config (defaults + overrides)
  -> POST /api/v1/generations {config: ...}
  -> GenerationService: domain, model, backend, ABC and token-budget validation
  -> immutable GenerationJob.config + request.json + queue JSON
  -> FilesystemJobQueue.claim -> Worker.run_job
  -> GGUF dispatch OR configured native/mock/ComfyUI adapter
  -> validate -> prepare -> plan -> generate -> decode -> finalise
  -> audio / score / intermediates / effective_config / manifest
  -> atomic job updates -> SSE/polling -> UI
```

- `GenerationConfig.model` already carries `checkpoint`, `revision`, `vae`, `vae_revision`, compute backend, quantization, offload, memory budget and offline flags. It has no per-task GPU selection.
- `config_from_overrides()` recursively merges JSON defaults and validates the domain model. Historical empty/null checkpoints normalize to `default`.
- `model.checkpoint` and `model.vae` are independent persisted fields. Native `ModelManager.acquire()` passes both model and VAE, plus their revisions, to `YuE2Pipeline.from_pretrained()`.
- The native cache key includes model, VAE, their revisions, GPU and runtime/loading controls. Sampling changes do not unnecessarily reload weights.
- Generation history keeps its frozen config; project edits affect future takes. Retry, duplicate and score regeneration reuse/override that snapshot.
- Request defaults come from `configs/yue2.defaults.json`, not a merge of every `YUE2_*` Settings value. Some environment compute/quantization/offload/memory defaults therefore do not govern submitted full configs as the documentation suggests. Define precedence explicitly when extending settings.
- The GGUF adapter reads `studio-model.json` in the selected checkpoint directory and sets `yue2.model_gguf=<selected filename>`. It always sets `yue2.vae_gguf=yue2-vae-f16.gguf`; nondefault task VAE choices are rejected by shared GGUF parameter validation.
- ComfyUI sends a checkpoint basename to a remote graph; VAE comes from its checkpoint and GPU ownership is external. Local manager controls must accurately report that limit.

### Hugging Face download and inventory

```text
Settings / ModelDownloads component
  -> GET /api/v1/models/hub?repo_id=...&revision=...
  -> HfApi.model_info(files_metadata=True)
  -> select one filename
  -> POST /api/v1/models/downloads
  -> persistent download JSON + FastAPI background task
  -> resolve immutable commit SHA / size / disk check
  -> sequential hf_hub_download(selected file + recognized companions)
  -> models/hub/<owner>--<repo>--<identity>/studio-model.json
  -> complete download record
  -> capabilities inventory + generation schema invalidation
```

- Downloader accepts arbitrary valid HF repository IDs, revisions and a single `.gguf` or `.safetensors` file. It is already more general than a fixed URL; extend it.
- Repository browse only returns those two extensions and sizes. There is no branch/tag listing, description/card/config metadata, multi-file or full-repository mode, or discovery search.
- GGUF companions are currently fixed: F16 VAE and four YuE2 sidecars (model config, generation config, tokenizer, VAE config). If any companion is absent remotely, only the main file is downloaded.
- Native companions are a small fixed allow-list; sharded weights and arbitrary repository layouts are not handled.
- Identity uses repository + resolved commit + filename. `studio-model.json` stores repository, resolved revision and selected filename, not a full model descriptor or dedicated registry.
- Inventory is computed live by `CapabilityService.local_models()`: configured native model/VAE paths, immediate sibling directories and children of `models/hub`. Native directories need `config.json` and literal `model.safetensors`; extra directories require `model_type` YuE2/YuE2 VAE. GGUF detection depends on studio metadata and a filename beginning `yue2-3b-`.
- Existing identifiers are absolute directory paths. Preserve these as legacy references during any registry migration.
- Download records expose file counters/current file, not downloaded byte counts, speed or ETA. States are `downloading`, `complete`, `failed`.
- JSON writes are atomic; application-level repository installation is not. Files land directly in the inventory-visible destination; failures leave files behind. HF handles some cache/incomplete-file behavior, but the studio has no aggregate verify/register stages or integrity guarantee.
- Disk check uses known selected/companion sizes plus 1 GiB, on the destination volume during execution. Unknown sizes count as zero; there is no preflight preview.
- Download exclusion uses a process-local threading lock. `get()` marks a downloading record with another PID interrupted; this is unsuitable for multiple API processes. Deployment defaults currently use one API process.
- Legacy `scripts/download_models.sh` remains a separate native model/VAE setup path and must keep working without redownloading valid existing weights.

## Phase 1 readiness diagnosis (historical snapshot)

### The reported warning has a reproducible runtime cause here

The completed local download `mdl_0munpushjc2k595pf` is:

```text
repository: audio-cpp/Yue2-3B-GGUF
commit:     eb14a51700bf8baac825a690b2f3b24a01239f85
file:       yue2-3b-q4_0.gguf
directory:  models/hub/audio-cpp--Yue2-3B-GGUF--c9b7db1eb092
main bytes: 2,665,645,728
```

The main file, `yue2-vae-f16.gguf`, all four sidecars and `studio-model.json` exist. Structural inventory detection returns `present=True`. However, `CapabilityService.local_models()` then changes it to `present=False` because the configured audio.cpp CLI is not executable/available:

```text
audio.cpp CLI is not installed. Run make install-audiocpp.
```

`apps/web/components/settings/model-downloads.tsx:101` displays the generic warning whenever a complete download has no matching capability entry with `present=True`. It hides the actual inventory `problem`. The installed list also labels that same entry missing without exposing this cause.

**This warning does not depend on whether a task has selected the model.** A stale/loading capabilities response can also temporarily take the warning branch, because unresolved inventory is treated as not ready.

Differential checks made without changing source or installing a runtime:

1. Assert that this complete download is `present`: fails with the missing-CLI reason (reproduces the warning).
2. Inspect it structurally through `_describe_model`: files pass the current presence checks.
3. Mock only executable discovery: inventory becomes `present=True`, `problem=None`.
4. Merge its explicit checkpoint through `config_from_overrides`: the path survives unchanged.
5. Call worker `is_gguf_model(path)`: returns true.
6. Call API `_validate_model(config)` without the runtime mock: refuses with `MODEL_NOT_FOUND` and the CLI reason, before enqueueing inference.

Presence checks are not content/checksum validation. These checks prove the immediate blocker and configuration propagation; they do not prove GPU inference works after installing audio.cpp.

Runnable local reproduction from the repository root (read-only; expected to fail while the CLI is unavailable):

```bash
PYTHONPATH=packages/core:services/api .venv-api/bin/python - <<'PY'
from pathlib import Path
from app.services.capabilities import CapabilityService
from yue2_studio_core.settings import get_settings

path = str(Path('models/hub/audio-cpp--Yue2-3B-GGUF--c9b7db1eb092').resolve())
service = CapabilityService(get_settings())
assert service._describe_model(path, 'model')['present'], 'Installation files are incomplete'
entry = next(model for model in service.local_models() if model['id'] == path)
assert entry['present'], f"Readiness blocker: {entry['problem']}"
PY
```

### A separate schema bug offered unavailable models (fixed in 2A)

`CapabilityService.schema()` builds model options with `enabled=entry.present` and `disabled_reason=entry.problem`. `packages/core/yue2_studio_core/parameters.py:186` then overwrites each option without a capability with `enabled=mode_supported` (true for non-mode parameters).

The resulting unavailable GGUF option had **`enabled=True` and a missing-CLI disabled reason simultaneously**. `ModelSelector` trusted `enabled`, so it offered this option; the API later refused the request. Phase 2A fixed annotation centrally, with shared-schema and API regression tests.

### Why selection may be absent or change

- The completed download shows a `Use for a song` link only when inventory says present. With the current CLI blocker, that action is unavailable.
- That link otherwise opens `/create?model=<absolute-directory>`. `app/create/page.tsx` writes it to `model.checkpoint`; CreateForm submits its effective configuration. The API saves it and the worker consumes it. There is no general loss of checkpoint between API and worker.
- Downloading does not automatically change the configured default. Opening Create directly still selects the `default` sentinel; this is intentional until explicit selection or configuration changes.
- CreateForm preset application replaces all settings except the song prompt; reset drops settings except the prompt. Both can remove an explicitly selected checkpoint/VAE and restore defaults. Preserve device/model/VAE selection deliberately when implementing the task UX.
- Model selection currently lives inside Advanced Settings. VAE selection is already a separate control, but its options are static standard/legacy and it is disabled for GGUF. There is no compatible installed-VAE browser.
- During Phase 1, Create submission gated prompt/input/token budget without model readiness. Phase 2A now gates the backend model option as well. Project settings still lacks Create's GGUF-specific disabling context.
- Settings currently shows read-only environment/path cards, downloads/inventory and presets. There is no local `Browse File`/directory picker or path-validation endpoint to repair; this feature must be added. Its existing `Browse files` action browses Hugging Face, and the browser file input elsewhere uploads cover audio rather than selecting server model paths.
- During Phase 1, `resolve_model_choice('default')` bypassed CLI checks and worker GGUF dispatch checked the raw sentinel. Phase 2A unified reference resolution and made default dispatch use the resolved installation, retaining the submitted sentinel in history.

## Hardware and runtime findings

### Hardware today

- `SystemInfoService._gpus()` uses NVML for all physical GPUs: index, name, driver, compute capability, total/used/free VRAM, utilization, temperature and processes.
- Worker heartbeats contain CUDA-visible devices, torch/CUDA/runtime versions, model manager state, current job and GPU memory/peak data. API prefers worker-visible devices, then supplements with NVML when its own environment does not hide devices.
- Device matching lacks stable UUID identity. API and worker may have different `CUDA_VISIBLE_DEVICES`; physical and logical indices can be mixed. Use worker-reported logical indices plus stable hardware identifiers.
- CPU RAM/available memory, FP16/runtime capability detail and accurate per-model residency are absent. BF16 uses a compute-capability heuristic rather than a fully reported probe.
- Current `model_recommendation()` ranks three fixed YuE2 Q4/Q8/BF16 filenames with published peak values, reserving max(20%, 1 GiB). It does not evaluate actual installed/discovered descriptors or runtime availability and hardcodes a 3B parameter capacity.
- `vram_risk()` is a second fixed native-model heuristic using physical GPU 0, independent of selected GPU and checkpoint. Capability FP8 gating also probes physical GPU 0.
- Storage in `/system/info` reports `DATA_DIR` volume; downloads may be on a different model volume.
- Fresh stopped heartbeats can be considered online because online detection uses timestamp alone. GGUF children are not represented in native manager state and are excluded from worker-PID-only accounting.

### GPU selection today

`PUT /api/v1/system/device` validates a 0–31 index and available devices when known, then atomically writes `data/runtime-settings.json`. The manager reads it dynamically. No restart is required today.

During idle heartbeat processing, a changed device triggers adapter `end_job()` and manager `release_if_device_changed()`. The next native job acquires on the selected device. A running generation is allowed to finish before idle release.

This is deferred switching, without an acknowledged command, admission barrier, immediate reload, release verification, failure rollback or displayed transition stages. `pending_restart` actually means selected/active differ, not a required restart. Native acquisition rereads the device setting rather than consistently using the job's initial device snapshot, leaving a loading-time placement race to fix.

Native release clears manager references, calls pipeline `close()`, runs GC and empties CUDA caches/IPC cache on the old device. Adapter-held references must be cleared as well. Close exceptions are logged/swallowed; unload failure and release verification are not represented. The manager has a loaded boolean, not lifecycle states.

Audio.cpp executes per job and is terminated/waited on cancellation or cleanup; it has no persistent CLI session to eagerly reload. Track the child/runtime state accurately and route explicit Load/Unload behavior according to backend capabilities. An external ComfyUI server remains responsible for its own GPU resources.

### Shutdown today

- Worker installs SIGINT/SIGTERM handlers; stop sets cancellation for the active operation. `Worker.run()` has a `finally` that stops heartbeat, calls adapter shutdown, releases the manager and writes a stopped heartbeat.
- Native shutdown clears adapter references and explicitly releases the pipeline. Thus explicit cleanup already exists; extend and harden it.
- If adapter shutdown raises, later manager cleanup can be skipped. Use nested cleanup/finally and explicit error state.
- API lifespan has startup and `yield` but no worker shutdown coordination. Stopping only the API leaves the separately started worker running. `make dev` signals its process group; `make stop` signals API and worker.
- Cover transcription is a separate process with termination semantics; its Python model references currently rely on child process exit. Include child cleanup in runtime shutdown coverage.
- Hard OS termination cannot execute Python hooks. Detect abandoned runtime/download records on restart and report the distinction from graceful cleanup.

## Implementation decisions to preserve

1. Extend the existing architecture: shared domain/metadata and compatibility rules; API for validated persisted configuration/downloads; worker for placement, memory checks and lifecycle. Browser renders backend decisions.
2. Reuse Store atomic writes and filesystem locks for registry/runtime commands. Introduce only the small command/ack mechanism needed for load/unload/switch; no broker or worker HTTP server is needed for the local deployment.
3. Keep downloaded, validated, registered, compatible/inference-ready, and currently loaded states independent. Ready does not depend on task selection or current residency. Preserve legacy `present` consumers temporarily as an explicitly defined compatibility projection.
4. Keep existing checkpoint/VAE strings, default/standard/legacy sentinels, project snapshots and manifests readable. New stable IDs need aliases/migration for existing absolute paths; migration discovers existing files without moving/deleting them or requiring downloads.
5. Model format support means a concrete adapter can honor the architecture, files, VAE and runtime settings. GGUF/safetensors extension or small file size alone is insufficient. Unknown metadata stays null/Unknown; heuristic capacity estimates are separate from exact descriptor fields.
6. Use existing download/status polling. Persist measured bytes and phase transitions; unknown totals produce indeterminate progress. Investigate the pinned HF client's progress hooks before choosing instrumentation, including cache hits, retries and Xet transfers.
7. Discover candidates with installed HF APIs and inspect chosen repositories. A quantization collection contains formats for other runtimes too; filter/evaluate them instead of claiming every result is usable.
8. File selection must select paths on the machine running the API. A normal browser file input does not reveal a usable server filesystem path. A scoped backend directory browser with path validation supports browser/local and remote-host use without requiring a desktop shell or GUI dependency. Manual paths remain optional.
9. Safe deletion checks queued/running task references, residency and active downloads under locks; accounts for shared files/VAEs, protects configured/external paths, and reports partial failures. UI confirmation names the model and reclaimable bytes. Preserve past manifests/history even if referenced weights are later removed.
10. Estimates use selected GPU free/usable memory, actual weight descriptors, VAE, cache/activation/workspace overhead, duration/decoder controls where relevant, precision/backend constraints, offload and system RAM. Reuse existing token-budget KV cache calculation. State provenance, assumptions, safety reserve and uncertainty explicitly.

## Plan: small independently completable slices

Each slice includes focused tests and a CONTEXT update. Phases 7–9 consolidate coverage/docs/validation; testing starts with the first code change.

| Phase / slice | Intended changes and files | Completion criterion |
|---|---|---|
| **1 — Analysis (done)** | This repository map, local reproduction, config trace, baseline checks and plan. | Root cause and adjacent selection/runtime issues documented; application code unchanged. |
| **2A — States and readiness (done)** | Shared model metadata/status types in core; capabilities, parameters, generation validation, API types and status UI extended. Legacy responses retained; option annotation/default resolution fixed centrally. | Complete files remain downloaded when runtime unavailable; API/UI share the precise blocker; unavailable options stay disabled; default/explicit configs resolve consistently. |
| **2B — Registry and migration (done)** | Shared filesystem registry/facts using Store; inventory delegates to it. Import configured paths and `studio-model.json`, recording nullable metadata/provenance. | Multiple native/GGUF variants and VAE entries have stable identity and preserved path aliases; re-import is idempotent; no weight movement/redownload; exact parameter counts are not guessed. |
| **2C — Validation and deletion (done)** | Shared structural format/architecture/sidecar/VAE checks; focused API registry actions in existing model routes; job-reference checks/file leases/deletion journal. | Corrupt/unsupported/incomplete states are distinct; delete refuses active references and updates registry safely; shared/external files and failed cleanup handled; Inspect/Validate APIs tested. |
| **3A — Hardware facts (done)** | Extend worker heartbeat probes, `system_info.py`, shared hardware facts and API types. Add system RAM and stable GPU identity; fix stopped-worker detection and selected-device precision checks. | GPU/RAM/storage facts and runtime availability have clear provenance; mock/no-GPU paths work; logical indices map correctly under hidden/reordered GPUs. |
| **3B — Capacity and recommendations (done)** | A backend estimation/recommendation service reusing shared model descriptors and KV cache logic; existing recommendation routes become compatible projections. Configurable reserves. | Every GPU has capacity estimates; installed/candidate rankings deterministic with explanations, backend/VAE/offload checks and unknown states; boundary/missing-data tests pass. |
| **4A — HF inspection/discovery (done)** | Extend `model_downloads.py` through a focused HF helper, current routes and descriptors. Repo/card/config/files metadata, refs, immutable commit, single/selected/repository previews (transfers in 4B), related quantized candidate discovery. | Existing single-file request still works; invalid/private/missing repo/revision/file cases actionable; previews use the actual destination disk and compatibility assessment. |
| **4B — Atomic downloads and measured progress (done)** | Shared download states and existing manager, private staging/file leases, pinned SDK byte instrumentation, verified registry publication and interruption retry/cleanup. Existing polling/API defaults retained; all three selection modes transfer. | Queued → Downloading → Verifying → Registering → complete/readiness result; actual per-file/overall bytes/rate/ETA; unknown totals honest; corrupt/partial content not admitted as valid; interrupted/resumed/cached transfers tested. |
| **5A — Worker lifecycle and commands (done)** | Worker-owned lifecycle snapshots, session/process leases, serial queued Load/Unload acknowledgements, shared validation/VRAM checks and actual native priming/placement. API forwards commands and reads runtime. | Native load/unload/failure/in-use observable; GGUF per-job activity/unknown residency explicit; no false GGUF/vLLM preload; API imports no torch; mocks cover transitions/recovery/ordering. |
| **5B — Dynamic GPU switch (done)** | Existing command admission/claim, captured job device, verified managed cleanup, target preparation/commit and rollback; `/system/device` acknowledgement and GPU UI polling. | Active job settles; mock tests prove serial allocation and failure handling. Native torch reloads without restart; VAE/vLLM/audio.cpp retain honest lazy/per-job semantics. Physical smoke remains pending. |
| **5C — Shutdown (done)** | Priority session stop, cancellation settlement, independent cleanup steps, child reap, API coupling/download bookkeeping and interrupted-job recovery. | Mock/CPU fixture tests prove admission, ordering, failure records and recovery; build/type checks pass. Physical GPU shutdown smoke remains pending. |
| **6A — Installed models UI** | Dedicated `/models` area and navigation using current shell/cards/dialogs/query hooks. Adapt Settings links instead of maintaining duplicate inventory UI. | Inspect/Use/Load/Unload/Delete, real metadata and independent states, actionable blockers, exact deletion confirmation, accessible responsive cards and empty/error/loading states. |
| **6B — Download/recommendation UI** | Repository inspect → revision/files → preview → progress → validation/install outcome; reuse current download component/hook, System capacity and recommended cards. | All selection modes, actual bytes/file/status/speed/ETA, retry/errors and uncertainty visible; no stale-inventory warning; responsive/keyboard behavior verified. |
| **6C — Task selection and path browser** | Create and project configuration forms expose Model/VAE/GPU; backend-compatible options; preserve explicit choices on presets; scoped server path browser in Settings with reset/validation. | Selected model/VAE/device reach worker; invalid choices block submission with reasons; changing VAE never replaces model; path selection works for API-host filesystem; frontend holds UI state only. |
| **7 — Coverage consolidation** | Existing pytest suites plus a minimal frontend test setup chosen after inspecting current tooling needs. Offline HF fixtures/mocked runtime; no real GPU in CI. | Metadata/quantization/parameters/estimates/states, single/repository downloads and failure cleanup, registration/deletion, runtime APIs, switch/shutdown, selectors/progress/confirmation/responsive coverage. |
| **8 — Documentation** | README and existing architecture/model/API/setup/troubleshooting docs; backend extension guide only where useful. | Documents describe shipped behavior, migration, formats/runtime limits, HF workflow, estimates, GPU switching, shutdown/deletion and adding an adapter. |
| **9 — Validation** | Run unit/integration/worker checks, TS/ESLint/Python syntax, production build and appropriate smoke checks. Resolve baseline gate failures separately and transparently. | Existing native YuE2 and legacy records stay valid; all applicable gates pass; actual hardware checks, if available, distinguished from mocks; every outstanding limitation recorded. |

## Baseline validation results (2026-09-30)

| Command / check | Result |
|---|---|
| `make test` | Unit stage: **90 passed, 2 skipped, 1 failed**. Existing `test_workflow_mapping_matches_the_reference_workflow` expects root `yue2_full.json`, which is absent. Make stops before later targets. |
| `.venv-api/bin/python -m pytest tests/unit/test_model_downloads.py tests/unit/test_model_manager.py tests/unit/test_audiocpp_backend.py -q` | **4 passed, 1 skipped**; manager module requires worker environment. |
| `.venv-yue2/bin/python -m pytest tests/unit/test_model_manager.py -q` | **9 passed**; mock pipeline residency checks, no physical GPU work. |
| `.venv-api/bin/python -m pytest tests/integration -q` (outside sandbox, timeout 120 seconds) | **75 passed** in 58.69 seconds; one Starlette/AnyIO deprecation warning. Includes API, project lifecycle and mock worker integration. |
| Initial sandbox integration run; bounded verbose repeat | Stalled before first test in `TestClient.__enter__` / AnyIO portal startup. Initial run interrupted; bounded repeat exited 124 after 40 seconds. Same suite succeeds outside sandbox. Do not diagnose this as an application inference regression. |
| `npm run typecheck` in `apps/web` | Passed. |
| `npm run lint` in `apps/web` | Passed; Next.js warns `next lint` is deprecated for Next 16. |
| Local readiness differential checks | Reproduced missing-CLI warning, structurally complete installation, overwritten option-enabled flag and intact checkpoint propagation. |

Production build and real GPU/HF download smoke tests were not run in this analysis task. No runtime was installed and no model files/configuration were changed. Frontend tests do not yet exist in package scripts. Existing mock API tests still validate against configured local model inventory, so clean CI without downloaded native weights needs explicit temporary model fixtures when expanding coverage.

## Known issues and information still needed

- Immediate local GGUF blocker: audio.cpp CLI unavailable. The next code phase can proceed using fixtures; actual inference validation needs a built compatible CLI and CUDA toolchain.
- Baseline unit gate: missing `yue2_full.json`. The generated mapping exists; do not invent a reference workflow merely to make the assertion pass. Determine whether an authoritative reference can be restored or the test should be made self-contained in a separate, scoped change.
- Exact metadata must come from headers/configuration/repository metadata, not model names. Current recommendations use shared metadata/heuristics and explicit reserves; filename quantization hints remain unverified and never populate validated facts.
- Determine actual audio.cpp VAE selection/runtime option support against the pinned executable before promising independent GGUF VAE load behavior. Native model/VAE selection already has a working seam.
- Full-repository transfer is implemented; unknown sizes and SDK cache storage remain documented limits. Sharded/alternate weights may be stored without runtime support or independent registry selection. Do not turn successful content transfer into a compatibility claim.
- Physical GPU switching/release/rollback needs a suitable machine and idle testing window later; mocked lifecycle checks cannot prove CUDA residency release.
- Server file browsing will target the API host. If a desktop-native picker becomes a requirement, establish the supported launcher/platform explicitly before adding OS GUI integration.
- No missing information currently blocks Phase 6A. Ask for user input only if a concrete future decision cannot be resolved from existing configuration or requirements.

## Reference verification

Inspected the user-provided [GitHub project](https://github.com/Farzine/Music_Studio_YuE2), [HF example repository](https://huggingface.co/audio-cpp/Yue2-3B-GGUF), and [quantized collection](https://huggingface.co/models?other=base_model:quantized:m-a-p/YuE2-3B).

The HF card lists GGUF variants, F16/F32 VAEs and sidecars and attributes its memory measurements to an RTX 5090 server-mode benchmark. Its BF16 measurement uses an F32 VAE, whereas this application's GGUF adapter fixes an F16 VAE. The collection also includes formats for other backends (such as MLX), so discovery alone is not compatibility evidence. Treat remote catalogs as changing inputs, not constants.

## Change log

- **Phase 1:** added `CONTEXT.md` only. Completed architectural map, warning reproduction/root cause, selection/model/VAE/GPU/shutdown traces, baseline validation and phased plan.
- **Phase 2A:** implemented shared preflight descriptors, readiness/selector fixes, consistent default dispatch, precise status UI and focused regression tests/documentation. Next: Phase 2B registry persistence and migration.
- **Phase 2B:** added persistent installation facts, idempotent legacy import, stable identities/path aliases, completed-download registration, live readiness and explicit registry recovery. Tests/docs updated. Next: Phase 2C content/structural validation and safe deletion.
- **Phase 2C:** added structural/checksum validation, inspection/confirmed deletion APIs, recovery journals, file leases and serialized admission, shared architecture/VAE checks and expanded offline tests/docs. Next: Phase 3A hardware facts.

- **Phase 3A:** shared CPU/RAM/precision facts, UUID GPU merging, nullable sensors, authoritative worker CUDA selection, stopped-worker detection, selected-device capability/VRAM checks and System UI/docs/tests completed. Next: Phase 3B capacity and recommendations.

- **Phase 3B:** shared capacity/metadata-aware model estimates, configurable reserves, deterministic explanations, generic inventory recommendation API, shared task VRAM projection and System UI/docs/tests completed. Daemon interruption recovered. Next: Phase 4A HF inspection/discovery.

- **Phase 4A:** repository/card/config/files/ref inspection, immutable selection previews/destination storage, quantized-lineage discovery, shared candidate estimates, existing Settings flow and offline/API/live-metadata tests/docs completed. Existing single-file transfer remains compatible; selected/repository transfers and atomic byte progress are next (4B).

- **Phase 4B:** single/selected/repository atomic transfers, shared download transitions/byte accounting, scoped pinned-SDK progress, private staging/verification/locked registration, retry/recovery/partial cleanup, existing Settings progress/selection UX and tests/docs completed. Next: Phase 5A worker lifecycle and load/unload commands.

- **Phase 5A:** explicit worker lifecycle, native Load/Unload command APIs/acknowledgements, session/process ownership, queue/deletion coordination, validation/memory guards, real native priming and model/VAE placement, audio.cpp process facts and System observability completed with mock/unit/worker/API tests/docs. Next: Phase 5B dynamic GPU switching/release verification and rollback.

- **Phase 5B:** worker-acknowledged GPU switch stages, managed release checks, target preparation/commit-last selection, failure rollback, captured native/transcription device and CUDA visibility mapping, accessible GPU selector polling and regression/docs updates completed. No physical GPU smoke performed. Next: Phase 5C shutdown hardening.

- **Phase 5C:** graceful worker/API stop requests, cancellation settlement, independent cleanup/error acknowledgements, child group termination/reaping, interrupted-job/download recovery and System/docs/tests completed. Physical GPU shutdown smoke remains pending. Next: Phase 6A Installed Models UI.
