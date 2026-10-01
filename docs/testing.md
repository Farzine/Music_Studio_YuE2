# Testing model management

## Backend and worker

```bash
make test-unit
make test-integration
make test-worker
```

The pytest suites use temporary storage, offline Hugging Face metadata/transfers
and mock GPU pipelines. Actual model weights or CUDA devices are not required.
Lifecycle/switch/shutdown tests also exercise CPU-only fixture child processes.
`make test-worker` uses the configured worker environment for model-manager tests.
For all worker control tests in that environment:

```bash
.venv-yue2/bin/python -m pytest -q tests/unit/test_model_manager.py tests/unit/test_gpu_switch.py tests/unit/test_shutdown.py tests/unit/test_worker_commands.py
```

The original ComfyUI graph is a provenance-documented fixture under `tests/fixtures`.
Workflow parity tests do not require or restore the optional runtime `yue2_full.json`.

## Frontend

```bash
cd apps/web
npm ci
npm test
npx playwright install --with-deps chromium
npm run test:browser
```

If Google Chrome is already installed, use `PLAYWRIGHT_CHANNEL=chrome npm run
test:browser` instead of installing Chromium. Helper tests use Node's test runner;
rendered tests use the single Playwright development dependency. The browser
configuration follows Playwright's [web server](https://playwright.dev/docs/test-webserver)
and [network interception](https://playwright.dev/docs/network) APIs.

Browser tests launch their own Next process on `127.0.0.1:3107`, refuse reuse of
an existing server and stop their process group afterward. Run browser tests and
build/type checks sequentially because Next regenerates `.next` types/cache.
API forwarding points to an unused loopback port. Tests intercept all `/api/v1`
requests; unexpected routes fail their fixture contract. No API/worker, model
files, Hugging Face connection, production download/delete or device switch is
needed. Fixtures are test inputs, not claims about the host's hardware.

The same scenarios run at desktop (1440×1000) and mobile (390×844) widths:

- Task Model/VAE/GPU independence, preserved preset/reset choices, submitted
  resource configuration, unavailable saved choices and accessible errors.
- Installed metadata/Use Model, pending versus acknowledged load state, exact
  deletion confirmation, running-task blockers, safe Cancel focus and restoration.
- HF commit-pinned inspection, complete-repository preview, insufficient storage
  gating, preview invalidation, measured/unknown progress, verification/registration
  states, failed-transfer retry errors and confirmed partial cleanup.
- GPU switch acknowledgement/failure states, keyboard activation and preserved
  prior selection; read-only recommendations, reasons and Unknown metadata.
- Host file selection, directory path validation/errors, registration/reset,
  invalidation after path edits, keyboard modal dismissal and focus restoration.
- Project Model/VAE/GPU persistence and no generation navigation after failed save.

Core pages include horizontal-overflow assertions. These checks cover the tested
widths and keyboard interactions; they are not a full accessibility audit or
pixel comparison. Screenshots/traces are retained on failure under ignored
`apps/web/test-results`. GitHub's `web-tests.yml` runs helper/browser tests without
a GPU and uploads failure artifacts.

## Build and syntax checks

After the browser server has stopped:

```bash
npm run build
npm run typecheck
npm run lint
```

From the repository root:

```bash
.venv-api/bin/python -m compileall -q packages services scripts
git diff --check
```

Real native/audio.cpp inference, CUDA release/rollback and graceful shutdown
require a controlled hardware smoke test. Passing mock/browser tests does not
establish physical GPU residency cleanup or guarantee a model fits VRAM.
