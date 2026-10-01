# Hugging Face model inspection, downloads and discovery

In **Settings → model downloads**, enter `owner/repository` and an optional
branch, tag or commit. Select **Inspect repository**, choose a model weight file,
choose single-package, selected-file or complete-repository content, then
**Preview download**. The preview shows selected content, total bytes when
known, free disk space at the model destination, prerequisites and a GPU estimate.
**Download model** uses the resolved immutable commit, including when a branch
changes after inspection. Changing repository, revision or file clears the preview.

The revision input offers discovered branches/tags and also accepts explicit
commits. **Discover YuE2 variants** inspects a bounded set of repositories declaring
`base_model:quantized:m-a-p/YuE2-3B`, the tag used by the
[reference collection](https://huggingface.co/models?other=base_model:quantized:m-a-p/YuE2-3B).
Other base models can be queried through the discovery API. Hub lineage tags do
not prove compatibility. Results are inspected, never automatically downloaded.
An empty discovery result does not stop inspection of a manually entered ID.

The existing [audio.cpp example repository](https://huggingface.co/audio-cpp/Yue2-3B-GGUF)
is supported through its file/configuration metadata, rather than a repository-ID
exception. Small JSON configurations are read at the resolved commit, with a
1 MiB limit, duplicate-key checks and no remote Python execution. Branch/tag
listing or optional JSON failures appear as warnings; missing facts stay Unknown.

## Metadata and estimates

- Every repository file has its name, extension, nullable byte size and LFS SHA256
  when supplied by Hugging Face. Git object IDs are not presented as SHA256.
- Candidates have shared model descriptors and adapter requirements. Model and
  VAE entries are separate; the browser's model list excludes identified decoders.
- Architecture comes from configuration. Parameter count is only populated from
  explicit positive integer `parameter_count` or `num_parameters` configuration
  metadata. A `3B` name or tensor storage size never becomes a parameter count.
- Filename quantization/precision hints are labelled **unverified**; they do not
  populate validated quantization fields. Actual weight headers are checked after
  download through structural validation.
- Declared architecture, file layout and sidecars use the same core adapter rules
  as local installations. Unsupported families, native shards/alternate filenames
  and pre-quantized native safetensors receive explicit blockers. This phase adds
  management/discovery, not a runtime for arbitrary Hugging Face architectures.
- Candidate estimates use the existing memory engine, known remote cache dimensions
  and bundled VAE bytes, current selected GPU/runtime and installed native VAE.
  A declared native latent-width mismatch blocks compatibility. Estimates remain
  heuristic and uninstalled/unvalidated candidates are never runnable or loaded.
  See [memory assumptions](model-recommendations.md).

## Inspection and preview API

All paths below have the `/api/v1` prefix:

| Method | Path | Request |
|---|---|---|
| POST | `/models/hub/inspect` | `repo_id`, optional `revision`, optional `device_index` |
| POST | `/models/hub/preview` | Above plus primary `filename`, optional `mode`, optional `selected_files` |
| GET | `/models/hub/discover` | `base_model` (default `m-a-p/YuE2-3B`), `limit` (1–20; default 10), optional `device_index` |
| GET | `/models/hub` | Existing lightweight response contract: `repo_id`, resolved `revision`, weight `files` |

Inspection returns repository/card facts, revisions, all files, candidate metadata,
warnings, selected-device `assessments` and `by_gpu` assessments. Raw downloaded
JSON configuration is internal to estimation and is not returned by the API.
Missing hardware yields unknown/no assessments, rather than a claimed GPU fit.
Discovery preserves per-repository errors so one inaccessible result does not
discard the others. Repositories and assessments have deterministic ordering.

Preview selection modes:

- `single` (default): primary file plus the existing adapter's recognized related
  files, preserving the old downloader's package behavior. An incomplete GGUF
  repository previews the primary file alone and explains missing prerequisites.
- `selected`: primary file and explicitly chosen repository-relative files,
  deduplicated. Missing required sidecars are reported.
- `repository`: all files at that commit, including alternate weights, examples
  and documentation. The primary filename remains explicit for registration.

The preview checks the nearest existing parent of the destination under
`MODELS_DIR/hub`, including when that directory is a separate mounted filesystem.
It creates no installation or registry entries.
`total_bytes` is null if any selected size is unknown; `known_bytes` is the actual
metadata lower bound. `disk_status` distinguishes sufficient, insufficient and
unknown totals. `existing_bytes` is the observed size of requested files already at
that installation, pending verification; `remaining_known_bytes` is the known
additional content. This amount plus 1 GiB headroom exceeding free space sets
`can_download=false`. Free space is checked again before transfer and when the SDK
resolves previously unknown sizes. Unknown totals cannot guarantee enough space.

Remote `studio-model.json` and `.cache/huggingface/` content are reserved local
control paths. Select other files explicitly if a repository contains them;
complete-repository mode refuses such a selection.

## Transfer, validation and registration

All three preview modes also work in the Settings download panel and download API.
The primary filename remains explicit. Complete-repository mode preserves alternate
weights as content but registers only that primary model for selection. It does not
add a runtime for unsupported architectures, shards or encodings.

Each job pins its commit and selected files before queuing. Transfers use the
existing Hugging Face SDK's HTTP/Xet implementation, authentication and cache/resume
behavior, with private staging at `MODELS_DIR/hub/.downloads/<job_id>`. Staging is
excluded from model inventory. The final directory stays absent until all requested
content is received, file sizes and supplied LFS SHA256 checksums pass, and known
GGUF/safetensors structures and the package are checked. Unsupported encodings or
missing prerequisites remain unvalidated/unavailable rather than becoming Ready.

The manager writes installation metadata, takes the existing registry lock and
publishes the directory by rename on the same filesystem. Registration failures
roll newly published content back into private staging for retry. Existing file
leases protect task/resident content. These steps handle process interruption;
the filesystem JSON store does not promise database transactions or power-loss
durability.

Default single-package destination identities remain backward compatible.
Different file selections use separate identities to avoid overwriting an existing
installation; shared weights can therefore occupy disk twice. Repeated identical
requests verify existing content and reuse it without transfer. Damaged installed
content is preserved: inspect/delete that exact installation before downloading
again. The downloader does not silently replace it.

The workflow is **Queued → Downloading → Verifying → Registering → Downloaded**.
The API retains `complete` for the last state. Inventory separately reports
validation, compatibility and inference availability; completion does not mean
loaded on a GPU. Supported content is available only when its package, runtime
and compatible VAE prerequisites are satisfied.

## Real progress and recovery

The existing two-second frontend polling shows overall and current-file bytes,
percentages only when totals are known, sampled speed, estimated ETA, status,
errors and attempt number. SDK callbacks count actual logical file bytes processed;
resume/cache/Xet deduplication can differ from network-interface bytes. A cache hit
has verified file bytes but no invented transfer speed. Xet file preallocation is
never counted as downloaded progress. Unknown totals stay Unknown until SDK
metadata or the completed file establishes its size. Progress snapshots are
persisted at most four times a second.

Only one download runs across API processes. **Retry** retains the pinned commit,
selection and SDK partial cache, rechecks disk space and revalidates content. A bad
staged file is fetched again rather than trusted from cache. Jobs whose owner died,
or whose running transfer no longer owns its execution lease, become interrupted
failures when polled. A live owner's queued job still awaits its background task;
download cancellation/shutdown coordination is not added here.

**Remove partial files** applies only to failed jobs and removes their private
staging directory. Its reported `partial_bytes` measures allocated disk blocks,
independently of download progress. It never deletes an installed model or a legacy
unregistered directory. Old completed/failed jobs remain readable; retry upgrades
legacy interrupted jobs by resolving their original revision once.

Storage checks cover the model destination with a 1 GiB reserve. SDK caches outside
that directory may use another filesystem; cache growth, unknown sizes and other
processes' writes cannot be guaranteed by a preview. Insufficient space during
transfer becomes an actionable failed job with private staging retained for retry.

The SDK is pinned to `huggingface-hub==0.36.2`. Its public download function has no
progress callback, so one private progress-factory seam is isolated in
`huggingface_transfer.py` and scoped to studio transfers. HTTP resume, Xet and
concurrent callback tests must pass before upgrading that dependency.

Dedicated model pages and browser interaction tests follow in the later UX/testing
phases. Native VAE download registration/role selection is still pending; use the
existing configured/local VAE workflow. Standalone GGUF VAE selection is not offered
by the current audio.cpp adapter, which uses the package's bundled F16 VAE.

## Errors and authentication

Invalid IDs, revisions or unsafe file paths return 422. Missing repositories,
revisions or files return 404 with actionable messages. Hugging Face deliberately
does not distinguish all private/not-found responses: check the repository ID and
API host token. Gated/unauthorized repositories explain authorization/terms; use
`HF_TOKEN` or the SDK's existing login on the API host. Tokens are never returned
to the browser. Network failures request a retry and do not echo raw upstream
exception URLs/credentials. Optional metadata failures preserve warnings and
Unknown fields. An explicitly missing GPU returns 422.

No GPU load, device switch, generation selection or model registration occurs
from remote candidate assessment. Existing installations/paths stay intact.
