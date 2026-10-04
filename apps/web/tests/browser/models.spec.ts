import { test, expect } from "@playwright/test";
import { assessment, expectNoOverflow, gpus, mockStudio, model, recommendation, taskChoices } from "./fixtures";

test("task resource choices stay independent across presets and are sent in the request", async ({ page }) => {
  const studio = await mockStudio(page);
  await page.goto("/create");
  const model = page.getByRole("combobox", { name: "Model", exact: true });
  const vae = page.getByRole("combobox", { name: "VAE", exact: true });
  const gpu = page.getByRole("combobox", { name: "GPU", exact: true });
  await model.selectOption("/models/alternate");
  await expect(vae).toHaveValue("standard");
  await vae.selectOption("/models/alternate-vae");
  await expect(model).toHaveValue("/models/alternate");
  await gpu.selectOption("1");
  await page.getByRole("button", { name: "Balanced", exact: true }).click();
  await page.getByRole("button", { name: "Reset to defaults", exact: true }).click();
  await expect(model).toHaveValue("/models/alternate");
  await expect(vae).toHaveValue("/models/alternate-vae");
  await expect(gpu).toHaveValue("1");
  await expect(model.getByRole("option", { name: "Unsupported architecture" })).toHaveCount(0);
  await page.getByRole("textbox", { name: /^Style/ }).fill("Fixture instrumental pop");
  await page.getByRole("textbox", { name: /^Lyrics/ }).fill("[Verse]\nOriginal fixture words");
  await expectNoOverflow(page);
  await page.route("**/api/v1/generations", (route) => route.fulfill({ status: 422, json: { error_message: "Fixture submission captured" } }));
  const request = page.waitForRequest((r) => r.url().endsWith("/api/v1/generations") && r.method() === "POST");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  expect((await request).postDataJSON().config.model).toMatchObject({ checkpoint: "/models/alternate", vae: "/models/alternate-vae", device_index: 1 });
  await expect(page.getByText("Fixture submission captured", { exact: true })).toBeVisible();
  studio.assertHealthy();
});

test("an unavailable saved resource keeps its value and blocks submission with an accessible reason", async ({ page }) => {
  const studio = await mockStudio(page);
  studio.responses["/generation/options"] = { ...taskChoices, valid: false, issues: ["Unsupported architecture"],
    models: [{ value: "/models/incompatible", label: "Unsupported architecture", enabled: false, disabled_reason: "Unsupported architecture" }] };
  await page.goto("/create?model=%2Fmodels%2Fincompatible");
  const selector = page.getByRole("combobox", { name: "Model", exact: true });
  await expect(selector).toHaveValue("/models/incompatible");
  await expect(selector).toHaveAttribute("aria-invalid", "true");
  await expect(selector).toHaveAccessibleDescription("Unsupported architecture");
  await expect(page.getByRole("button", { name: "Create", exact: true })).toBeDisabled();
  await expect(page.getByText("Unsupported architecture", { exact: true }).first()).toBeVisible();
  expect(studio.requests.some((r) => r.path === "/generations" && r.method === "POST")).toBe(false);
  studio.assertHealthy();
});

test("download progress uses byte totals and stays indeterminate when totals are unknown", async ({ page }) => {
  const studio = await mockStudio(page);
  const download = { id: "download-fixture", repo_id: "fixture/weights", filename: "fixture.gguf", revision: "main", mode: "single",
    status: "downloading", attempt: 1, completed_files: 0, total_files: 1, downloaded_bytes: 50, total_bytes: 100, percentage: 50,
    current_file: "fixture.gguf", current_file_bytes: 50, current_file_total_bytes: 100, current_file_percentage: 50, bytes_per_second: 10, eta_seconds: 5 };
  studio.responses["/models/downloads"] = { items: [download] };
  await page.goto("/models/download");
  const progress = page.getByRole("progressbar", { name: "Overall download progress for fixture.gguf", exact: true });
  await expect(progress).toHaveAttribute("value", "50");
  await expect(page.getByText(/50.0%.*ETA 5s/)).toBeVisible();
  studio.responses["/models/downloads"] = { items: [{ ...download, total_bytes: null, percentage: null, eta_seconds: null,
    current_file_total_bytes: null, current_file_percentage: null }] };
  await page.getByRole("button", { name: "Refresh download & inventory status" }).click();
  await expect(progress).not.toHaveAttribute("value");
  await expect(page.getByText(/Unknown total.*ETA unknown/)).toBeVisible();
  await expect(page.getByRole("progressbar", { name: "File progress: fixture.gguf" })).not.toHaveAttribute("value");
  for (const status of ["verifying", "registering"]) {
    studio.responses["/models/downloads"] = { items: [{ ...download, status }] };
    await page.getByRole("button", { name: "Refresh download & inventory status" }).click();
    await expect(page.getByText(status, { exact: true })).toBeVisible();
  }
  await expectNoOverflow(page);
  studio.assertHealthy();
});

test("deletion names exact files, starts on Cancel, restores focus and sends the confirmation token", async ({ page }) => {
  const studio = await mockStudio(page);
  studio.responses["/models/model-fixture/deletion-preview"] = { registry_id: model.registry_id, path: model.path, original_path: model.path,
    confirmation_token: "fixture-confirmation", estimated_reclaimed_bytes: 1024, files: [{ path: "model.safetensors", bytes: 1024 }],
    blockers: [], can_delete: true, warning: "These installation files will be permanently deleted." };
  studio.responses["/models/model-fixture"] = { complete: true };
  await page.goto("/models");
  await expect(page.getByRole("heading", { name: model.label })).toBeVisible();
  await expect(page.getByText("Unknown", { exact: true }).first()).toBeVisible();
  const remove = page.getByRole("button", { name: "Delete", exact: true });
  await remove.click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText(model.path!);
  await expect(dialog).toContainText("Estimated disk space reclaimed");
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  expect(studio.requests.filter((r) => r.method === "DELETE")).toHaveLength(0);
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(remove).toBeFocused();
  await remove.click();
  await dialog.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(studio.requests.find((r) => r.method === "DELETE")?.body).toEqual({ confirmed_path: model.path, confirmation_token: "fixture-confirmation" });
  await expectNoOverflow(page);
  studio.assertHealthy();
});

test("running-task deletion blockers disable confirmation", async ({ page }) => {
  const studio = await mockStudio(page);
  studio.responses["/models/model-fixture/deletion-preview"] = { registry_id: model.registry_id, path: model.path,
    estimated_reclaimed_bytes: 1024, files: [], blockers: ["Required by running task gen-fixture"], can_delete: false,
    warning: "Installation is protected while a task is using it." };
  await page.goto("/models");
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog.getByText("Required by running task gen-fixture")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Delete", exact: true })).toBeDisabled();
  expect(studio.requests.some((r) => r.method === "DELETE")).toBe(false);
  studio.assertHealthy();
});

test("GPU selection waits for acknowledgement and displays failure without claiming a switch", async ({ page }) => {
  const studio = await mockStudio(page);
  const command = { id: "switch-fixture", device_index: 1, status: "running", worker_online: true,
    progress: { stage: "unloading", message: "Unloading model from GPU 0…" }, error: null };
  studio.responses["/system/device"] = { ...gpus, switch_command: command };
  await page.goto("/system");
  const target = page.getByRole("radio", { name: /CUDA GPU 1/ });
  await target.focus();
  await page.keyboard.press("Space");
  await expect(page.getByText("Switching to GPU 1…", { exact: true })).toBeVisible();
  await expect(page.getByText("Unloading model from GPU 0…", { exact: true })).toBeVisible();
  await expect(target).toBeDisabled();
  await expect(page.getByRole("radio", { name: /CUDA GPU 0/ })).toBeChecked();
  expect(studio.requests.find((r) => r.path === "/system/device")?.body).toEqual({ device_index: 1 });
  studio.responses["/system/gpus"] = { ...gpus, switch_command: { ...command, status: "failed",
    progress: { stage: "restored", message: "Previous GPU 0 restored" }, error: { error_code: "CUDA_OOM", error_message: "GPU 1 has insufficient memory." } } };
  await expect(page.getByText("GPU switch failed", { exact: true })).toBeVisible();
  await expect(page.getByText("GPU 1 has insufficient memory.", { exact: true })).toBeVisible();
  await expect(target).toBeEnabled();
  await expect(page.getByRole("radio", { name: /CUDA GPU 0/ })).toBeChecked();
  await expectNoOverflow(page);
  studio.assertHealthy();
});

test("recommendations show reasons and Unknown metadata; evaluating another GPU is read only", async ({ page }) => {
  const studio = await mockStudio(page);
  await page.goto("/models/recommended");
  await expect(page.getByText(assessment.reasons[0], { exact: true })).toBeVisible();
  await expect(page.getByText("Unknown", { exact: true }).first()).toBeVisible();
  await page.getByText("Memory estimate details", { exact: true }).click();
  await expect(page.getByText("Fixture estimate, not a load guarantee.", { exact: true })).toBeVisible();
  studio.responses["/system/model-recommendation"] = { ...recommendation, device_index: 1, recommended: null,
    items: [{ ...assessment, device_index: 1, runnable: false, status: "cannot_run", reasons: ["Insufficient safe VRAM budget"] }] };
  await page.getByRole("combobox", { name: "Evaluate GPU" }).selectOption("1");
  await expect(page.getByText("Insufficient safe VRAM budget", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Use Model", exact: true })).toHaveCount(0);
  expect(studio.requests.some((r) => r.path === "/system/device")).toBe(false);
  await expectNoOverflow(page);
  studio.assertHealthy();
});

test("Settings selects a host file, returns keyboard focus, validates, registers and clears it", async ({ page }) => {
  const studio = await mockStudio(page);
  const path = "/models/fixture-native/model.safetensors";
  await page.route("**/api/v1/models/local/browse*", (route) => route.fulfill({ json: {
    roots: ["/models"], path: "/models/fixture-native", parent: "/models", truncated: false,
    items: [{ name: "model.safetensors", path, kind: "file", bytes: 1024 }],
  } }));
  studio.responses["/models/local/validate"] = { path, kind: "file", exists: true };
  studio.responses["/models/local/register"] = { model };
  await page.goto("/settings");
  await page.getByRole("combobox", { name: "Selection type" }).selectOption("file");
  const browse = page.getByRole("button", { name: "Browse File" });
  await browse.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(browse).toBeFocused();
  await page.keyboard.press("Enter");
  await dialog.getByRole("button", { name: "Select", exact: true }).click();
  await dialog.getByRole("button", { name: "Use selected path" }).click();
  await expect(page.getByRole("textbox", { name: "Selected path" })).toHaveValue(path);
  expect(studio.requests.find((r) => r.path === "/models/local/validate")?.body).toEqual({ path, kind: "file" });
  await page.getByRole("button", { name: "Register installation" }).click();
  await expect(page.getByText(/Registered Fixture YuE2 Native/)).toBeVisible();
  await page.getByRole("button", { name: "Clear selection", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Selected path" })).toHaveValue("");
  await expect(page.getByRole("button", { name: "Register installation" })).toBeDisabled();
  await expectNoOverflow(page);
  studio.assertHealthy();
});

test("Use Model prefills only the checkpoint and runtime loading waits for worker facts", async ({ page }) => {
  const studio = await mockStudio(page);
  const command = { id: "load-fixture", operation: "load", status: "queued", worker_online: true };
  studio.responses["/models/model-fixture/load"] = command;
  studio.responses["/models/runtime-commands/load-fixture"] = command;
  await page.goto("/models");
  await page.getByRole("button", { name: "Load", exact: true }).click();
  await expect(page.getByText("Load request: queued.", { exact: true })).toBeVisible();
  await expect(page.getByText("Not loaded", { exact: true })).toBeVisible();
  await expect(page.getByText("Currently loaded", { exact: true })).toHaveCount(0);
  studio.responses["/models/runtime-commands/load-fixture"] = { ...command, status: "succeeded" };
  studio.responses["/models"] = { items: [{ ...model, currently_loaded: true }] };
  await expect(page.getByText("Currently loaded", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Use Model", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Model", exact: true })).toHaveValue(model.id);
  await expect(page.getByRole("combobox", { name: "VAE", exact: true })).toHaveValue("standard");
  studio.assertHealthy();
});

test("HF inspection pins revisions and invalidates an unsafe or stale download preview", async ({ page }) => {
  const studio = await mockStudio(page);
  const files = [{ name: "model.safetensors", bytes: 1024, extension: ".safetensors" }, { name: "config.json", bytes: 128, extension: ".json" }];
  const commit = "a".repeat(40);
  studio.responses["/models/hub/inspect"] = { repo_id: "fixture/weights", revision: commit, requested_revision: "v1",
    revisions: [{ kind: "tag", name: "v1", commit_hash: commit }], files, warnings: [],
    candidates: [{ model: { ...model, id: "hf:fixture/weights", role: "model", is_local: false, inference_ready: false },
      required_files: ["model.safetensors", "config.json"], missing_files: [] }] };
  const preview = { repo_id: "fixture/weights", revision: commit, requested_revision: "v1", filename: "model.safetensors",
    mode: "repository", files, total_bytes: 1152, free_bytes: 100, safety_margin_bytes: 1024, destination: "/models/fixture-install",
    missing_required_files: [], warnings: ["Insufficient disk space"], disk_status: "insufficient", can_download: false };
  studio.responses["/models/hub/preview"] = preview;
  await page.goto("/models/download");
  await page.getByRole("textbox", { name: "Hugging Face repository" }).fill("fixture/weights");
  await page.getByLabel("Branch, tag or commit", { exact: true }).fill("v1");
  await page.getByRole("button", { name: "Inspect Repository", exact: true }).click();
  await expect(page.getByText(`Resolved commit: ${commit}`, { exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Download content" }).selectOption("repository");
  await page.getByRole("button", { name: "Preview Download", exact: true }).click();
  await expect(page.getByRole("button", { name: "Start Download", exact: true })).toBeDisabled();
  expect(studio.requests.find((r) => r.path === "/models/hub/preview")?.body).toMatchObject({ repo_id: "fixture/weights", revision: commit,
    filename: "model.safetensors", mode: "repository" });
  studio.responses["/models/hub/preview"] = { ...preview, free_bytes: 2**30, can_download: true, disk_status: "sufficient", warnings: [] };
  await page.getByRole("button", { name: "Preview Download", exact: true }).click();
  await expect(page.getByRole("button", { name: "Start Download", exact: true })).toBeEnabled();
  await page.getByRole("textbox", { name: "Primary model filename" }).fill("different.safetensors");
  await expect(page.getByRole("button", { name: "Start Download", exact: true })).toHaveCount(0);
  expect(studio.requests.some((r) => r.path === "/models/downloads" && r.method === "POST")).toBe(false);
  await expectNoOverflow(page);
  studio.assertHealthy();
});

test("failed transfers show retry errors and confirm exact partial-file cleanup", async ({ page }) => {
  const studio = await mockStudio(page);
  studio.responses["/models/downloads"] = { items: [{ id: "failed-fixture", repo_id: "fixture/failed", filename: "partial.gguf", revision: "main",
    status: "failed", error: "Checksum mismatch; retry this file.", downloaded_bytes: 30, total_bytes: 100, percentage: 30,
    partial_bytes: 30, completed_files: 0, total_files: 1 }] };
  await page.route("**/api/v1/models/downloads/failed-fixture/retry", (route) => route.fulfill({ status: 409, json: { error_message: "Another download is running. Try again when it finishes." } }));
  studio.responses["/models/downloads/failed-fixture/partial"] = { complete: true };
  await page.goto("/models/download");
  await expect(page.getByText("Checksum mismatch; retry this file.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Retry download" }).click();
  await expect(page.getByText("Another download is running. Try again when it finishes.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Remove partial files", exact: true }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("fixture/failed · partial.gguf");
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  expect(studio.requests.some((r) => r.method === "DELETE")).toBe(false);
  await dialog.getByRole("button", { name: "Remove partial files", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(studio.requests.find((r) => r.path === "/models/downloads/failed-fixture/partial")?.method).toBe("DELETE");
  studio.assertHealthy();
});

test("path errors remain actionable and changing a validated directory prevents stale registration", async ({ page }) => {
  const studio = await mockStudio(page);
  await page.route("**/api/v1/models/local/validate", (route) => {
    const body = route.request().postDataJSON();
    return body.path === "/models/native" ? route.fulfill({ json: { path: body.path, kind: "directory", exists: true } })
      : route.fulfill({ status: 422, json: { error_message: "Path is outside configured model roots." } });
  });
  await page.goto("/settings");
  const path = page.getByRole("textbox", { name: "Selected path" });
  await path.fill("/outside/model");
  await page.getByRole("button", { name: "Validate path" }).click();
  await expect(page.getByText("Path is outside configured model roots.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Register installation" })).toBeDisabled();
  await path.fill("/models/native");
  await page.getByRole("button", { name: "Validate path" }).click();
  await expect(page.getByRole("button", { name: "Register installation" })).toBeEnabled();
  await path.fill("/models/another");
  await expect(page.getByRole("button", { name: "Register installation" })).toBeDisabled();
  expect(studio.requests.some((r) => r.path === "/models/local/register")).toBe(false);
  studio.assertHealthy();
});

test("project settings preserve resource choices and a failed save never navigates to generation", async ({ page }) => {
  const studio = await mockStudio(page);
  studio.responses["/projects/project-fixture"] = { project: { id: "project-fixture", title: "Fixture project" }, generations: [] };
  studio.responses["/projects/project-fixture/config"] = { source: "project", config: { model: { checkpoint: model.id, vae: "standard", device_index: 0 },
    prompt: { mode: "full", style: "Fixture style", lyrics: "Original words" } } };
  await page.route("**/api/v1/projects/project-fixture/config", async (route) => {
    if (route.request().method() === "GET") return route.fallback();
    expect(route.request().postDataJSON().config.model).toMatchObject({ checkpoint: model.id, vae: "/models/alternate-vae", device_index: 1 });
    return route.fulfill({ status: 422, json: { error_message: "Fixture incompatible configuration" } });
  });
  await page.goto("/projects/project-fixture/settings");
  await page.getByRole("combobox", { name: "VAE", exact: true }).selectOption("/models/alternate-vae");
  await page.getByRole("combobox", { name: "GPU", exact: true }).selectOption("1");
  await expect(page.getByRole("combobox", { name: "Model", exact: true })).toHaveValue(model.id);
  await page.getByRole("button", { name: "Save and generate a new version", exact: true }).click();
  await expect(page.getByText("Fixture incompatible configuration", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/projects\/project-fixture\/settings$/);
  await expectNoOverflow(page);
  studio.assertHealthy();
});

test("installed model repair previews missing files and queues measured recovery", async ({ page }) => {
  const studio = await mockStudio(page);
  studio.responses["/models"] = { items: [{ ...model, huggingface_repo: "owner/repository", files_complete: false,
    inference_ready: false, inference_status: "files_missing", problem: "Missing bundled VAE" }] };
  studio.responses[`/models/${model.registry_id}/repair-preview`] = {
    registry_id: model.registry_id, repo_id: "owner/repository", revision: "a".repeat(40), filename: "model.safetensors",
    destination: model.path, repair_files: [{ name: "vae.gguf", bytes: 1024 }], download_bytes: 1024,
    free_bytes: 8192, safety_margin_bytes: 1024, can_repair: true, confirmation_token: "repair-token",
  };
  studio.responses[`/models/${model.registry_id}/repair`] = { id: "mdl_repair", status: "queued" };
  await page.goto("/models");
  await page.getByRole("button", { name: "Repair installation" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(/vae.gguf/)).toBeVisible();
  await expectNoOverflow(page);
  await dialog.getByRole("button", { name: "Repair and validate" }).click();
  await expect(page.getByRole("link", { name: "Repair queued — view progress" })).toBeVisible();
  expect(studio.requests.find((r) => r.path.endsWith("/repair") && r.method === "POST")?.body).toEqual({ confirmation_token: "repair-token" });
  studio.assertHealthy();
});

test("missing registered installs can be removed while uninstalled defaults are not installed cards", async ({ page }) => {
  const studio = await mockStudio(page);
  studio.responses["/models"] = { items: [
    { ...model, is_local: false, inference_ready: false, download_status: "missing", inference_status: "files_missing" },
    { ...model, id: "remote/optional-vae", registry_id: null, label: "Never installed optional VAE", is_local: false,
      registration_status: "discovered", inference_ready: false, download_status: "missing" },
  ] };
  await page.goto("/models");
  await expect(page.getByRole("button", { name: "Remove missing installation" })).toBeEnabled();
  await expect(page.getByText("Never installed optional VAE")).toHaveCount(0);
  studio.assertHealthy();
});
