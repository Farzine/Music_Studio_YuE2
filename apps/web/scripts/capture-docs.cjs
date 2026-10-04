// Run against a live studio: node scripts/capture-docs.cjs GENERATION_ID PROJECT_ID
// Captures desktop views of real pages. It never submits a generation, deletes files, or switches GPUs.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../../..');
const output = path.join(root, 'docs/assets/screenshots');
const [generation, project] = process.argv.slice(2);
if (!generation || !project) throw new Error('Supply a real generation and project ID.');
const base = process.env.STUDIO_URL || 'http://127.0.0.1:3000';
(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true, args: ['--disable-gpu', '--disable-dev-shm-usage'] });
  const previous = path.join(output, 'manifest.json');
  const captures = process.env.CAPTURE_RESUME && fs.existsSync(previous) ? JSON.parse(fs.readFileSync(previous, 'utf8')).captures.filter(c => c.device === 'desktop') : [];
  try {
    const diagram = await browser.newPage({ viewport: { width: 1500, height: 1160 }, deviceScaleFactor: 1 });
    await diagram.setContent('<html><body style="margin:0">' + fs.readFileSync(path.join(root, 'docs/assets/workflow.svg'), 'utf8') + '</body></html>');
    await diagram.screenshot({ path: path.join(root, 'docs/assets/workflow.png'), fullPage: true });
    await diagram.close();
    const device = 'desktop';
    const viewport = { width: 1440, height: 1000 };
    const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
    page.setDefaultTimeout(30000);
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    async function shot(name) {
      await page.evaluate(() => document.fonts.ready);
      const modal = await page.getByRole('dialog').first().isVisible() || await page.getByRole('alertdialog').first().isVisible();
      await page.screenshot({ path: path.join(output, `${name}-${device}.png`), fullPage: !modal });
      const prior = captures.findIndex(c => c.name === name && c.device === device);
      if (prior >= 0) captures.splice(prior, 1);
      captures.push({ name, device, url: page.url().replace(base, ''), file: `${name}-${device}.png` });
      console.log('Captured', name, device);
      fs.writeFileSync(path.join(output, 'manifest.json'), JSON.stringify({ captured_at: new Date().toISOString(), generation, project, source: 'Live application and real API; no response fixtures', captures }, null, 2) + '\n');
    }
    async function open(url) {
      await page.goto(base + url, { waitUntil: 'networkidle', timeout: 60000 });
      await page.locator('main').waitFor();
      await page.waitForTimeout(1000);
    }
    for (const [name, url] of [
      ['dashboard','/'], ['create',`/create?from=${generation}`], ['library','/library'],
      ['projects','/projects'], ['project',`/projects/${project}`], ['project-settings',`/projects/${project}/settings`],
      ['generation',`/generations/${generation}`], ['score',`/scores/${generation}`],
      ['models','/models'], ['download','/models/download'], ['recommendations','/models/recommended'],
      ['system','/system'], ['settings','/settings'], ['about','/about'],
    ]) { if (process.env.CAPTURE_RESUME && captures.some(c => c.name === name && c.device === device)) continue; await open(url); await shot(name); }
    if (!process.env.CAPTURE_EXTRA) {
    await open(`/generations/${generation}`);
    await page.getByRole('button', { name: 'Download…', exact: true }).first().click();
    await page.getByRole('dialog').waitFor();
    await shot('audio-download');
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: 'Play', exact: true }).first().click();
    await page.waitForTimeout(1200);
    await shot('audio-player');
    await page.getByRole('button', { name: 'Pause', exact: true }).first().click();
    await open('/settings');
    await page.getByLabel('Selection type').selectOption('file');
    await page.getByRole('button', { name: 'Browse File', exact: true }).click();
    await page.getByRole('dialog').waitFor();
    await page.waitForTimeout(500);
    await shot('file-browser');
    await page.keyboard.press('Escape');
    await open('/models');
    const inventory = await (await page.request.get(base + '/api/v1/models')).json();
    const model = inventory.items.find(m => m.format === 'gguf');
    await shot('models');
    const card = page.locator(`#${model.registry_id}`);
    await card.getByRole('button', { name: 'Inspect', exact: true }).click();
    await page.getByRole('dialog').waitFor();
    await page.waitForTimeout(500);
    await shot('model-inspection');
    await page.keyboard.press('Escape');
    await card.getByRole('button', { name: 'Delete', exact: true }).click();
    await page.getByRole('alertdialog').waitFor();
    await shot('model-delete-confirmation');
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await card.getByRole('button', { name: 'Repair installation' }).click();
    await page.getByRole('dialog').waitFor({ timeout: 120000 });
    await shot('model-repair');
    await page.keyboard.press('Escape');
    await open(`/models/download?repo=${encodeURIComponent(model.huggingface_repo)}&revision=${model.commit_hash || model.revision}&file=${encodeURIComponent(model.filename)}`);
    await page.getByLabel('Hugging Face repository').fill(model.huggingface_repo);
    await page.getByRole('button', { name: 'Inspect Repository' }).click();
    await page.getByLabel('Primary model filename').waitFor({ timeout: 120000 });
    await page.getByLabel('Primary model filename').fill(model.filename);
    await shot('repository-inspection');
    await page.getByRole('button', { name: 'Review download' }).click();
    await page.getByRole('button', { name: 'Start Download', exact: true }).waitFor({ timeout: 120000 });
    await shot('download-preview');
    }
    await open(`/create?from=${generation}`);
    await page.getByRole('button', { name: /^Planning/ }).click();
    await shot('advanced-settings');
    await page.getByRole('button', { name: 'Save as preset' }).click();
    await page.getByPlaceholder('Preset name').waitFor();
    await shot('save-preset');
    await open(`/scores/${generation}`);
    await Promise.all([page.waitForResponse(r => r.url().endsWith('/scores/validate')), page.getByRole('button', { name: 'Validate', exact: true }).click()]);
    await shot('score-validation');
    await Promise.all([page.waitForResponse(r => r.url().includes('/compare')), page.getByRole('button', { name: 'Compare with source' }).click()]);
    await shot('score-comparison');
    await open('/library');
    await page.getByRole('tab', { name: 'Scores', exact: true }).click();
    await shot('library-scores');
    await open(`/generations/${generation}`);
    await page.getByRole('button', { name: 'More actions' }).click();
    await page.getByRole('menuitem', { name: 'Delete', exact: true }).click();
    await page.getByRole('alertdialog').waitFor();
    await shot('generation-delete-confirmation');
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    const detail = await (await page.request.get(base + `/api/v1/generations/${generation}`)).json();
    if (detail.generation.parent_generation_id) {
      await open(`/generations/${detail.generation.parent_generation_id}`);
      await shot('generation-incomplete');
    }
    if (errors.length) throw new Error(`${device} browser errors: ${errors.join('; ')}`);
    await page.close();
    fs.writeFileSync(path.join(output, 'manifest.json'), JSON.stringify({ captured_at: new Date().toISOString(), generation, project, source: 'Live application and real API; no response fixtures', captures }, null, 2) + '\n');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
