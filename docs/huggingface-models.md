# Hugging Face model inspection and discovery

In **Settings → model downloads**, enter `owner/repository` and an optional
branch, tag or commit. Select **Inspect repository**, choose a model weight file,
then **Preview download**. The preview shows selected content, total bytes when
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

The preview checks the nearest existing parent of configured `MODELS_DIR`, on
that destination's filesystem. It creates no installation or registry entries.
`total_bytes` is null if any selected size is unknown; `known_bytes` is the actual
metadata lower bound. `disk_status` distinguishes sufficient, insufficient and
unknown totals. Known content plus 1 GiB headroom exceeding free space sets
`can_download=false`. Free space must still be checked at transfer time.

**Current transfer boundary:** the existing download POST still accepts one
primary filename and recognized companions. Multi-file/repository previews are
available through the API; their atomic transfers, staging/recovery, verification
and measured byte/rate/ETA progress are the next Phase 4B. The UI currently submits
the existing single-file package mode. File-count progress remains honest; it is
not converted into a fabricated byte percentage. Dedicated model pages and browser
interaction tests follow in the later UX/testing phases.

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
