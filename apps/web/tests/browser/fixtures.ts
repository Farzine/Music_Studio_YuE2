import { expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { GenerationSchema, ModelEntry, ModelAssessment } from "../../types/api";

const configs = resolve(__dirname, "../../../../configs");
const registry: GenerationSchema = JSON.parse(readFileSync(resolve(configs, "parameter-registry.json"), "utf8"));
export const schema = { ...registry, backend: "native", capabilities: {}, parameters: registry.parameters.map((p) =>
  ({ ...p, enabled: p.native.supported, options: p.options?.map((o) => ({ ...o, enabled: true })) })) };
// API boundary fixtures only; never import these into application code.
export const model: ModelEntry = {
  id: "/models/fixture-native", role: "model", label: "Fixture YuE2 Native", path: "/models/fixture-native",
  present: true, is_local: true, is_default: true, bytes: 1024, problem: null, format: "safetensors", filename: "model.safetensors",
  source: "local", huggingface_repo: null, revision: null, commit_hash: null, registry_id: "model-fixture", aliases: [],
  created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z", architecture: "yue2", parameter_count: null,
  quantization: null, precision: "F16", backend: "native", tensor_element_count: null, checksum_sha256: null,
  vae_requirements: "Compatible native VAE required", download_status: "downloaded", files_complete: true,
  validation_status: "validated", deletion_status: "active", registration_status: "registered", compatibility_status: "supported",
  inference_status: "ready", inference_ready: true, currently_loaded: false,
  runtime_actions: { load: { allowed: true, reason: null }, unload: { allowed: false, reason: "Not loaded" } },
};
export const assessment: ModelAssessment = {
  id: model.id, registry_id: model.registry_id, label: model.label, repo_id: null, filename: model.filename,
  format: "safetensors", backend: "native", quantization: null, precision: "F16", architecture: "yue2", model_bytes: 1024,
  parameters: null, device_index: 0, status: "recommended", reasons: ["Estimated sufficient headroom; runtime loading is still required."],
  inference_ready: true, currently_loaded: false, runnable: true, peak_bytes: 4096, required_bytes: 4096, safe_budget_bytes: 8192,
  excess_bytes: 0, vae_id: "/models/fixture-vae", offload_supported: true, offload_requested: false,
  estimate: { basis: "heuristic", weights_bytes: 1024, weight_runtime_bytes: 1280, vae_bytes: 1024, vae_size_known: true,
    kv_cache_bytes: 1024, kv_source: "heuristic", runtime_overhead_bytes: 768, estimated_peak_bytes: 4096,
    conservative_peak_bytes: 5000, estimated_system_ram_bytes: 8192, assumptions: ["Fixture estimate, not a load guarantee."] },
};
export const recommendation = {
  device_index: 0, available_bytes: 8192, capacities: [], items: [assessment], by_gpu: [{ device_index: 0, items: [assessment] }],
  recommended: assessment, scenario: { compute_backend: "torch", memory_budget_gib: 40, vae: "standard", offload_ar: false },
  note: "Planning estimates, not load guarantees.",
};
const gpu = {
  index: 0, name: "Fixture GPU", selected: true, selectable: true, cuda_available: true, compute_capability: "8.9",
  memory_free_bytes: 20 * 2**30, memory_total_bytes: 24 * 2**30, memory_used_bytes: 4 * 2**30,
  precision_source: "worker_runtime", memory_source: "worker_heartbeat", fp16_supported: true, bf16_supported: true,
  fp8_supported: true, reported_by: "worker",
};
export const gpus = { selected_index: 0, active_index: null, devices: [gpu, { ...gpu, index: 1, selected: false }], worker_online: true };
export const system = {
  app: { yue2_backend: "native", max_concurrent_gpu_jobs: 1 }, gpus: [], driver_version: null, gpu_error: null,
  memory: { cpu_name: "Fixture CPU", logical_cpu_count: 8, total_bytes: 32 * 2**30, available_bytes: 24 * 2**30, source: "fixture" },
  disk: { total_bytes: 100 * 2**30, free_bytes: 80 * 2**30, used_bytes: 20 * 2**30, path: "/fixture-data" },
  worker: { online: true, workers: [{ online: true, backend: "native", model: {}, runtime: {}, gpu: {}, state: "idle" }] },
  queue: { depth: 0, by_status: {}, total_generations: 0 }, devices: gpus, models: {},
};
export const taskChoices = {
  models: [
    { value: "default", label: "Default native", enabled: true },
    { value: model.id, label: model.label, enabled: true },
    { value: "/models/alternate", label: "Alternate native", enabled: true },
    { value: "/models/incompatible", label: "Unsupported architecture", enabled: false, disabled_reason: "Unsupported architecture" },
  ],
  vaes: [{ value: "standard", label: "Standard VAE", enabled: true }, { value: "/models/alternate-vae", label: "Alternate VAE", enabled: true }],
  gpus: [{ value: 0, label: "GPU 0", enabled: true }, { value: 1, label: "GPU 1", enabled: true }],
  selected_device_index: 0, backend: "native", issues: [], valid: true, vae_requirement: "Compatible native VAE required",
};

export async function mockStudio(page: Page) {
  const requests: { path: string; method: string; body: unknown }[] = [];
  const errors: string[] = [];
  const unhandled: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const responses: Record<string, unknown> = {
    "/health": { status: "ok", ready: true, worker_online: true, backend: "native" },
    "/queue": { active: [], queued: [], depth: 0, max_concurrent_gpu_jobs: 1 },
    "/generations": { items: [] },
    "/models": { items: [model] }, "/models/capabilities": { backend: "native", capabilities: {}, modes: ["full", "melody", "off"], models: [model] },
    "/models/downloads": { items: [] }, "/generation/schema": schema,
    "/presets": { defaults: { model: { checkpoint: "default", vae: "standard", device_index: null },
      prompt: { mode: "full", style: "", lyrics: "" } }, items: [{ id: "preset_balanced", name: "Balanced", builtin: true, description: "Fixture preset",
      config: { model: { checkpoint: "default", vae: "standard", device_index: null }, prompt: { style: "", lyrics: "" } } }] },
    "/system/info": system, "/system/gpus": gpus, "/system/model-recommendation": recommendation,
    "/system/vram-estimate": { warning: null }, "/generation/options": taskChoices,
    // Budget estimation is tested through pytest; no tokenizer is needed for UI selection tests.
    "/generation/estimate": {},
  };
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    requests.push({ path, method: request.method(), body: request.postData() ? request.postDataJSON() : null });
    if (!(path in responses)) {
      unhandled.push(`${request.method()} ${path}`);
      await route.fulfill({ status: 500, json: { error_message: `Unexpected fixture request: ${path}` } });
    } else await route.fulfill({ json: responses[path] });
  });
  return { responses, requests, assertHealthy: () => { expect(errors).toEqual([]); expect(unhandled).toEqual([]); } };
}

export async function expectNoOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}
