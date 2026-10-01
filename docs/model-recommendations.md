# Model capacity and recommendations

The System page answers two different planning questions:

- **Model capacity:** a heuristic file-size and parameter envelope for each worker-visible GPU.
- **Recommended models:** assessments of actual registered model variants on the selected GPU, using available metadata and adapter prerequisites.

Neither is a successful GPU load test or a guarantee. The API never loads tensors.
Shared calculations live in `packages/core/yue2_studio_core/model_recommendations.py`.
The worker remains authoritative for GPU visibility, residency and runtime facts.

## Memory budget

The engine uses current free VRAM and reserves the larger of:

```text
GPU total VRAM × MODEL_VRAM_SAFETY_FRACTION
MODEL_VRAM_SAFETY_GIB
```

An idle, manager-owned model's PyTorch reserved memory may be counted as
**conditionally reclaimable**, capped at physical used memory. The response
explicitly requires unloading that model and clearing its allocator cache first.
Active-job allocations, CUDA contexts, unrelated processes and audio.cpp subprocess
memory are never assumed reclaimable. The current free value remains visible
separately. These estimates do not request an unload or switch a device.

Native YuE2 additionally applies its selected `memory_budget_gib` minus the
installed runtime's 2 GiB allocator reserve. A large GPU can therefore have a
smaller usable native budget until the task configuration is changed.

## Actual model estimates

The model VRAM estimate is the conservative sum of:

```text
expanded model weights + VAE weights + KV cache + runtime workspace
```

- Weight expansion uses `MODEL_WEIGHT_OVERHEAD_FACTOR`, default **1.25**. Native loading uses BF16; a declared parameter count supplies a two-byte-per-parameter lower bound, never a count inferred from a filename or file size.
- Native VAE weights run in FP32. Known FP32 file sizes are used directly; FP16/unknown stored precision reserves twice the file size, with any declared parameter count providing a four-byte lower bound. GGUF uses its adapter's bundled F16 VAE file. Unknown VAE costs use a configurable reserve.
- KV cost reuses the token budget's BF16 calculation: `layers × 2 × KV heads × head dimension × 2 bytes`, multiplied by the declared full context and two CFG branches. Missing cache metadata uses `MODEL_UNKNOWN_KV_GIB`. This is a conservative scenario, not the exact peak for a specific song.
- Runtime workspace uses `MODEL_RUNTIME_OVERHEAD_GIB`. The scenario assumes tiled decoding. Full waveform decode needs additional unprofiled memory; the task warning says that explicitly.
- Conservative peak adds a further 20% to expanded weights. Native AR offload does not receive a full-load discount: the installed runtime loads the whole model before offloading unused AR modules during synthesis.
- Loading/offload RAM is estimated as 1.5 times model-plus-VAE weights. Unknown or insufficient available host RAM lowers confidence. Container limits are not measured yet.

These coefficients are deliberate heuristics. The native runtime moves weights
between GPU and CPU across stages, so summing model and VAE costs can overestimate
the actual peak. There is no request-specific activation profile, quantization
kernel benchmark or observed-peak database yet. vLLM memory policy remains unknown
rather than borrowing a torch estimate and claiming compatibility.

## Capacity envelope

Generic capacity uses configured VAE/cache/workspace reserves, then divides the
remaining budget by the weight expansion factor. The comfortable file-size limit
adds 20% weight headroom; the conservative limit is another 20% below comfortable.
The upper limit has the configured safety reserve but less weight headroom.

Hypothetical parameter capacities use effective storage bits **Q4 4.5**, **Q5 5.5**,
**Q8 8.5**, and **BF16 16**. These include a small heuristic allowance for quantization
scales/blocks. They are not parameter counts for installed models and do not imply
that an installed adapter supports every quantization. BF16 hardware ineligibility
is shown separately. Real model parameter counts remain **Unknown** unless metadata
explicitly declares them.

## Capability states

| State | Meaning |
|---|---|
| Ready | Compatible, structurally validated, estimated headroom, and the worker reports this model/VAE already loaded. |
| Recommended | Validated prerequisites and conservative estimated headroom for the stated runtime/VAE scenario. |
| Supported | Estimated peak fits the safe budget, with less conservative headroom. |
| Possibly supported | A memory estimate fits but structural checks or RAM availability remain unconfirmed. |
| Not recommended | Safety/allocator margin, host RAM or competing GPU utilization makes the configuration a poor current fit. |
| Cannot run | An explicit format/runtime/file/VAE blocker, or estimated peak exceeds currently available memory. |
| Unknown / needs validation | Missing hardware, architecture, runtime, model size, decoder or unsupported estimate scenario. |

Each result includes reasons, memory components, provenance, safe budget and
excess bytes. A loaded model in active inference is not falsely declared unable
to run from a duplicate full-load estimate: its incremental headroom remains
unknown until work settles. `currently_loaded` and `inference_ready` remain
separate from capability status. A different VAE does not inherit the previous
configuration's Ready state.

Deterministic ordering is capability state, then estimated peak memory ascending,
then stable model path/ID. The first runnable installed model is the recommendation;
file size is not treated as a quality ranking. Candidate descriptors can be
assessed through the same shared engine, but uninstalled candidates are not
runnable. [Hugging Face discovery/inspection](huggingface-models.md) supplies remote
configuration and bundled VAE sizes to this same engine, without registering
candidates or claiming a successful load. Filename quantization hints remain
separate from validated facts. Native candidates also compare declared latent
width with the selected installed VAE.

## Configuration

Add these to `.env` before starting the API; changing GPU selection itself still
does not require a restart:

```dotenv
MODEL_VRAM_SAFETY_FRACTION=0.20
MODEL_VRAM_SAFETY_GIB=1
MODEL_RUNTIME_OVERHEAD_GIB=2
MODEL_UNKNOWN_KV_GIB=2
MODEL_UNKNOWN_VAE_GIB=2
MODEL_WEIGHT_OVERHEAD_FACTOR=1.25
```

Fractions must be in `[0, 1)`, GiB values nonnegative and at most 1,000,000,
and expansion factor in `[1, 100]`; NaN/infinity are rejected. Reducing reserves
changes only estimates, not actual runtime requirements or generation settings.

## API and troubleshooting

`GET /api/v1/system/model-recommendation` retains legacy `variants`, `recommended`,
`available_bytes`, `max_model_bytes` and `max_parameters` fields. `variants` now
projects registered model assessments; it no longer fabricates three benchmark
files. `max_model_bytes` is the selected GPU's comfortable heuristic capacity;
`max_parameters` is null because there is no universal count independent of
precision. Use `capacities[].quantizations[].approximate_parameters` instead.

New fields: `capacities`, selected-GPU `items`, `by_gpu`, `memory`, `scenario`,
and the effective `policy`. Optional query parameters:

```text
device_index=1
vae=standard          # legacy or a registered VAE path also works
compute_backend=torch # torch-eager or vllm
budget_gib=40          # native allocator budget, 8–512 GiB
offload_ar=false
```

An explicitly requested missing device returns 422. An offline worker produces
no runnable recommendation. Unknown hardware/data never becomes a positive fit.

- **Needs validation:** use `POST /api/v1/models/{registry_id}/validate`; validate both native model and VAE. Dedicated UI action buttons arrive in the later model-management UI phase.
- **Unknown native runtime:** start the updated native worker and check its heartbeat/runtime environment.
- **Missing audio.cpp:** run `make install-audiocpp`; file download and runtime availability remain separate.
- **Insufficient margin:** inspect `excess_bytes`, other GPU workloads, VAE choice and native allocator budget. AR offload cannot solve the full-model load requirement.
- **VAE mismatch:** choose a compatible decoder; model selection is not changed automatically.
- **Tiny or unknown capacity:** check free VRAM, reserves and worker-visible GPU mapping. An offline physical NVML card is not proof of CUDA compatibility.

The existing `/system/vram-estimate` task warning uses this same engine and the
actual chosen `model`/`vae`/offload/compute configuration. It returns a warning or
null, never changes requests, and explains its full-context/tiled assumptions.

## Extending backends

Extend shared metadata/validation and the worker adapter before advertising a
new format as runnable. Supply the real weight, VAE, cache and precision facts;
then add an explicit memory profile when the existing conservative estimate
cannot describe that runtime. Keep new profile checks and tests in the shared
recommendation domain, not React or routes. Never assume a smaller serialized
file means a compatible runtime or sufficient GPU memory.
