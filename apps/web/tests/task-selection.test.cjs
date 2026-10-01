const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { runInNewContext } = require("node:vm");
const ts = require("typescript");
const helpers = {};
runInNewContext(ts.transpileModule(readFileSync(require.resolve("../lib/config.ts"), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText, { exports: helpers });
const { preserveTaskSelection, getPath, setPath } = helpers;

test("applying or resetting presets retains only explicitly chosen resources", () => {
  const current = { model: { checkpoint: "/models/a", vae: "/vae/b", device_index: 3, compute_backend: "torch" } };
  const preset = { model: { checkpoint: "default", vae: "standard", device_index: 0, compute_backend: "vllm" } };
  const applied = preserveTaskSelection(preset, current);
  for (const key of ["checkpoint", "vae", "device_index"]) assert.equal(getPath(applied, `model.${key}`), current.model[key]);
  assert.equal(getPath(applied, "model.compute_backend"), "vllm");
  assert.equal(getPath(preset, "model.checkpoint"), "default");
  assert.equal(getPath(preserveTaskSelection({}, current), "model.device_index"), 3);
  assert.equal(getPath(preserveTaskSelection(preset, {}), "model.checkpoint"), "default");
  const changedVae = setPath(current, "model.vae", "/vae/c");
  assert.equal(getPath(changedVae, "model.checkpoint"), "/models/a");
  const changedModel = setPath(current, "model.checkpoint", "/models/c");
  assert.equal(getPath(changedModel, "model.vae"), "/vae/b");
});
