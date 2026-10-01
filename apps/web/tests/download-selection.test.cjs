const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { runInNewContext } = require("node:vm");
const ts = require("typescript");

// Compile the dependency-free UI helper with the project's installed compiler.
const exportsUnderTest = {};
runInNewContext(ts.transpileModule(readFileSync(require.resolve("../lib/download-selection.ts"), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText, { exports: exportsUnderTest });
const { downloadSelectionKey } = exportsUnderTest;

test("a download preview is invalidated by every meaningful selection change", () => {
  const source = ["owner/repo", "main", "weights.gguf", "selected", ["config.json", "vae.gguf"], 0];
  const original = downloadSelectionKey(...source);
  for (const [index, value] of [[0, "owner/other"], [1, "v2"], [2, "other.gguf"], [3, "repository"], [4, ["config.json"]], [5, 1], [5, undefined]]) {
    const changed = [...source];
    changed[index] = value;
    assert.notEqual(downloadSelectionKey(...changed), original);
  }
  assert.equal(downloadSelectionKey(" owner/repo ", " main ", " weights.gguf ", "selected", ["vae.gguf", "config.json"], 0), original);
  assert.deepEqual(source[4], ["config.json", "vae.gguf"]); // never mutate selection state
});
