/**
 * Mandatory acceptance workflow (21 steps) against the real running stack and
 * the real PhysioNet LUDB record 3 (bundled, ODC-By 1.0).
 *
 * LUDB leaves edge beats unannotated; on lead II of record 3 the beats with R
 * at about sample 199 and 4703 carry no reference P/QRS/T, so manual
 * annotations there do not collide with the reviewed reference annotations.
 * The test first removes non-reference annotations left on ludb/3 by earlier
 * runs (reference annotations are never touched).
 */
import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';

interface Ann {
  id: string;
  tier: string;
  label: string;
  lead: string | null;
  start_sample: number;
  end_sample: number | null;
  attributes: Record<string, unknown>;
  source: string;
  review_status: string;
  revision: number;
  provenance: Record<string, unknown>;
}

const BEAT = { p: [4573, 4640], qrs: [4674, 4729], r: 4703 };
const VIEW = [4450, 4850];

async function apiGet<T>(request: APIRequestContext, path: string): Promise<T> {
  const res = await request.get(`/api${path}`);
  expect(res.ok(), `${path} -> ${res.status()}`).toBeTruthy();
  return (await res.json()) as T;
}

async function viewRange(page: Page): Promise<[number, number]> {
  const txt = (await page.getByTestId('view-range').textContent()) ?? '';
  const m = /view \[(\d+), (\d+)\)/.exec(txt);
  expect(m, `view readout: ${txt}`).not.toBeNull();
  return [Number(m![1]), Number(m![2])];
}

async function setView(page: Page, a: number, b: number) {
  await page.getByTestId('view-start').fill(String(a));
  await page.getByTestId('view-end').fill(String(b));
  await page.getByTestId('view-go').click();
  await expect(page.getByTestId('view-range')).toContainText(`view [${a}, ${b})`);
}

async function sampleX(page: Page, s: number): Promise<{ x: number; y: number }> {
  const box = (await page.getByTestId('waveform-canvas').boundingBox())!;
  const [a, b] = await viewRange(page);
  return { x: box.x + ((s - a) / (b - a)) * box.width, y: box.y + 30 };
}

async function annIn(row: Locator, label: string, lo: number, hi: number): Promise<Locator> {
  const els = row.locator(`[data-testid^="ann-"][data-label="${label}"]`);
  const n = await els.count();
  for (let i = 0; i < n; i++) {
    const s = Number(await els.nth(i).getAttribute('data-start'));
    if (s >= lo && s <= hi) return els.nth(i);
  }
  throw new Error(`no ${label} with start in [${lo}, ${hi}] (${n} candidates)`);
}

async function describeAnn(el: Locator) {
  return {
    id: ((await el.getAttribute('data-testid')) ?? '').replace(/^ann-/, ''),
    label: await el.getAttribute('data-label'),
    start: Number(await el.getAttribute('data-start')),
    end: (await el.getAttribute('data-end')) || null,
    lead: (await el.getAttribute('data-lead')) || null,
  };
}

const key = (a: Ann) => `${a.tier}|${a.label}|${a.lead}|${a.start_sample}|${a.end_sample}|${JSON.stringify(a.attributes)}`;

test('21-step acceptance workflow on real LUDB data', async ({ page, request }) => {
  const dialogs: string[] = [];
  page.on('dialog', async (d) => {
    dialogs.push(d.message());
    await d.dismiss();
  });

  // ---- 1. app is running -------------------------------------------------
  const health = await apiGet<{ status: string; database: string }>(request, '/health');
  expect(health.status).toBe('ok');
  test.info().annotations.push({ type: 'database', description: health.database });
  const recs = await apiGet<{ id: string; dataset_id: string; name: string; fs: number; n_samples: number }[]>(request, '/recordings');
  const rec = recs.find((r) => r.dataset_id === 'ludb' && r.name === '3');
  expect(rec, 'ludb/3 must be registered (bundled sample)').toBeTruthy();
  expect(rec!.fs).toBe(500);
  for (const a of await apiGet<Ann[]>(request, `/recordings/${rec!.id}/annotations`)) {
    if (a.source === 'reference') continue;
    const r = await request.delete(`/api/annotations/${a.id}?revision=${a.revision}&confirm_reviewed_change=true`);
    expect(r.ok()).toBeTruthy();
  }
  const refBefore = (await apiGet<Ann[]>(request, `/recordings/${rec!.id}/annotations`)).map(key).sort();
  expect(refBefore.length).toBeGreaterThan(100);

  // ---- 2. open the frontend ----------------------------------------------
  await page.goto('/');
  await expect(page.getByTestId('dataset-select')).toBeVisible();

  // ---- 3. select a real dataset ------------------------------------------
  await page.getByTestId('dataset-select').selectOption('ludb');

  // ---- 4. select a recording ---------------------------------------------
  await page.getByTestId('recording-select').selectOption(rec!.id);
  await expect(page.getByTestId('status-bar')).toContainText('Loaded ludb/3');

  // ---- 5. waveform is displayed (real samples in mV) ----------------------
  await expect(page.getByTestId('waveform-canvas')).toBeVisible();
  await expect(page.getByTestId('view-range')).toContainText('view [0, 5000)');
  await expect(page.locator('[data-testid^="lead-label-"]')).toHaveCount(12);
  const c = await sampleX(page, 2500);
  await page.mouse.move(c.x, c.y);
  await expect(page.getByTestId('cursor-readout')).toContainText(/mouse sample \d+ .* I (-?\d+\.\d{3}|\[-?\d+\.\d{3}, -?\d+\.\d{3}\]) mV/);
  // reference annotations of the record are shown in their tiers
  await expect(page.getByTestId('tier-row-QRS Complex').locator('[data-testid^="ann-"]').first()).toBeVisible();

  // ---- 6. switch leads ----------------------------------------------------
  await page.getByTestId('leads-button').click();
  await page.getByTestId('leads-single').click();
  await page.getByTestId('lead-toggle-V1').check();
  await page.mouse.move(5, 500);
  await expect(page.locator('[data-testid^="lead-label-"]')).toHaveCount(2);
  await expect(page.getByTestId('lead-label-II')).toBeVisible();
  await expect(page.getByTestId('lead-label-V1')).toBeVisible();
  await page.getByTestId('annotation-lead').selectOption('V1');
  await page.getByTestId('annotation-lead').selectOption('II');
  await expect(page.getByTestId('annotation-lead')).toHaveValue('II');

  // ---- 7. zoom to a single beat ------------------------------------------
  await page.getByTestId('zoom-in').click();
  const [za, zb] = await viewRange(page);
  expect(zb - za).toBeLessThan(5000);
  const canvasBox = (await page.getByTestId('waveform-canvas').boundingBox())!;
  await page.mouse.move(canvasBox.x + canvasBox.width / 2, canvasBox.y + 30);
  await page.mouse.wheel(0, -300); // wheel zoom around the mouse
  const [wa, wb] = await viewRange(page);
  expect(wb - wa).toBeLessThan(zb - za);
  await setView(page, VIEW[0], VIEW[1]);
  await expect(page.getByTestId('view-range')).toContainText('span 800 ms');

  // ---- 8. create a P-wave interval ----------------------------------------
  await page.getByTestId('tool-annotate').click();
  await page.getByTestId('active-tier').selectOption('P Wave');
  await page.getByTestId('active-label').selectOption('P_wave');
  let p0 = await sampleX(page, BEAT.p[0]);
  let p1 = await sampleX(page, BEAT.p[1]);
  await page.mouse.move(p0.x, p0.y);
  await page.mouse.down();
  await page.mouse.move(p1.x, p1.y, { steps: 6 });
  await page.mouse.up();
  const pEl = await annIn(page.getByTestId('tier-row-P Wave'), 'P_wave', BEAT.p[0] - 3, BEAT.p[0] + 3);
  const P = await describeAnn(pEl);
  expect(P.lead).toBe('II');
  expect(Math.abs(Number(P.end) - BEAT.p[1])).toBeLessThanOrEqual(3);

  // ---- 9. create a QRS interval -------------------------------------------
  await page.getByTestId('active-tier').selectOption('QRS Complex');
  await page.getByTestId('active-label').selectOption('QRS_complex');
  p0 = await sampleX(page, BEAT.qrs[0]);
  p1 = await sampleX(page, BEAT.qrs[1]);
  await page.mouse.move(p0.x, p0.y);
  await page.mouse.down();
  await page.mouse.move(p1.x, p1.y, { steps: 6 });
  await page.mouse.up();
  const qEl = await annIn(page.getByTestId('tier-row-QRS Complex'), 'QRS_complex', BEAT.qrs[0] - 3, BEAT.qrs[0] + 3);
  const Q = await describeAnn(qEl);

  // ---- 10. create an R-peak point ------------------------------------------
  await page.getByTestId('active-tier').selectOption('Fiducial Points');
  await page.getByTestId('active-label').selectOption('R_peak');
  const rp = await sampleX(page, BEAT.r);
  await page.mouse.click(rp.x, rp.y);
  const rEl = await annIn(page.getByTestId('tier-row-Fiducial Points'), 'R_peak', BEAT.r - 3, BEAT.r + 3);
  const R0 = await describeAnn(rEl);
  expect(R0.end).toBeNull();

  // ---- 11. drag the R peak ---------------------------------------------------
  await page.getByTestId('tool-select').click();
  const rb = (await rEl.boundingBox())!;
  const track = (await page.getByTestId('tier-row-Fiducial Points').locator('[data-track]').boundingBox())!;
  const dx = 12;
  await page.mouse.move(rb.x + rb.width / 2, rb.y + rb.height / 2);
  await page.mouse.down();
  await page.mouse.move(rb.x + rb.width / 2 + dx / 2, rb.y + rb.height / 2, { steps: 3 });
  await page.mouse.move(rb.x + rb.width / 2 + dx, rb.y + rb.height / 2, { steps: 3 });
  await page.mouse.up();
  const expectedShift = Math.round((dx / track.width) * (VIEW[1] - VIEW[0]));
  const rMoved = page.getByTestId(`ann-${R0.id}`);
  const R1start = Number(await rMoved.getAttribute('data-start'));
  expect(Math.abs(R1start - (R0.start + expectedShift))).toBeLessThanOrEqual(1);
  expect(R1start).not.toBe(R0.start);
  await expect(page.getByTestId('prop-start')).toHaveValue(String(R1start));
  // undo / redo of the drag
  await page.getByTestId('undo').click();
  await expect(rMoved).toHaveAttribute('data-start', String(R0.start));
  await page.getByTestId('redo').click();
  await expect(rMoved).toHaveAttribute('data-start', String(R1start));

  // ---- 12. modify a morphology attribute -------------------------------------
  await page.getByTestId(`ann-${Q.id}`).click();
  await expect(page.getByTestId('prop-tier')).toHaveValue('QRS Complex');
  await page.getByTestId('attr-morphology').selectOption('notched');
  await expect(page.getByTestId('attr-morphology')).toHaveValue('notched');

  // ---- 13. save ------------------------------------------------------------------
  await page.getByTestId('save').click();
  await expect(page.getByTestId('status-bar')).toContainText('Saved: 3 created, 0 updated, 0 deleted');
  const saved = (await apiGet<Ann[]>(request, `/recordings/${rec!.id}/annotations?source=manual`)).sort((a, b) => a.start_sample - b.start_sample);
  expect(saved.map((a) => [a.tier, a.label, a.lead, a.start_sample, a.end_sample])).toEqual([
    ['P Wave', 'P_wave', 'II', P.start, Number(P.end)],
    ['QRS Complex', 'QRS_complex', 'II', Q.start, Number(Q.end)],
    ['Fiducial Points', 'R_peak', 'II', R1start, null],
  ]);
  expect(saved[1].attributes).toEqual({ morphology: 'notched' });

  // ---- 14. refresh the browser --------------------------------------------------
  await page.reload();
  await expect(page.getByTestId('recording-select')).toHaveValue(rec!.id);
  await expect(page.getByTestId('status-bar')).toContainText('Loaded ludb/3');
  await setView(page, VIEW[0], VIEW[1]);

  // ---- 15. exact persistence ------------------------------------------------------
  for (const a of saved) {
    const el = page.getByTestId(`ann-${a.id}`);
    await expect(el).toHaveAttribute('data-start', String(a.start_sample));
    await expect(el).toHaveAttribute('data-end', a.end_sample === null ? '' : String(a.end_sample));
    await expect(el).toHaveAttribute('data-label', a.label);
    await expect(el).toHaveAttribute('data-lead', 'II');
  }
  await page.getByTestId(`ann-${saved[1].id}`).click();
  await expect(page.getByTestId('attr-morphology')).toHaveValue('notched');
  await expect(page.getByTestId('prop-start')).toHaveValue(String(Q.start));
  await expect(page.getByTestId('history-list')).toContainText('r1 create');

  // ---- 16. run R-peak detection ---------------------------------------------------
  await page.keyboard.press('Escape');
  await page.getByTestId('auto-menu').click();
  await page.getByTestId('detect-all').click();
  await expect(page.getByTestId('status-bar')).toContainText(/scipy_pan_tompkins@[\d.]+: \d+ predictions on II/);

  // ---- 17. predictions are displayed separately --------------------------------------
  await setView(page, 0, 900);
  const predRow = page.getByTestId('prediction-row');
  const preds = predRow.locator('[data-testid^="pred-"]');
  await expect(preds.first()).toBeVisible();
  let edge: Locator | null = null;
  let refBeat: Locator | null = null;
  for (let i = 0; i < (await preds.count()); i++) {
    const s = Number(await preds.nth(i).getAttribute('data-start'));
    if (s > 150 && s < 250) edge = preds.nth(i);
    if (s > 600 && s < 700) refBeat = preds.nth(i);
  }
  expect(edge, 'prediction for the unannotated first beat').not.toBeNull();
  expect(refBeat, 'prediction for the first reference-annotated beat').not.toBeNull();
  const edgeStart = Number(await edge!.getAttribute('data-start'));
  // not yet an annotation
  const fid = page.getByTestId('tier-row-Fiducial Points');
  await expect(fid.locator(`[data-start="${edgeStart}"]`)).toHaveCount(0);

  // ---- 18. a prediction on a reviewed reference beat is refused; modify + accept another
  await refBeat!.click();
  await expect(page.getByTestId('prediction-review')).toBeVisible();
  await page.getByTestId('pred-accept').click();
  await expect(page.getByTestId('status-bar')).toContainText('Accept failed');
  await expect(page.getByTestId('status-bar')).toContainText('reviewed');

  await edge!.click();
  await expect(page.getByTestId('pred-sample')).toHaveText(String(edgeStart));
  const modified = edgeStart + 3;
  await page.getByTestId('pred-edit').fill(String(modified));
  await page.getByTestId('pred-edit').press('Enter');
  await expect(page.getByTestId('pred-sample')).toHaveText(String(modified));
  await page.getByTestId('pred-accept').click();
  await expect(page.getByTestId('status-bar')).toContainText(`modified and accepted -> R_peak @ ${modified}`);
  await expect(fid.locator(`[data-label="R_peak"][data-start="${modified}"]`)).toHaveCount(1);
  const algo = await apiGet<Ann[]>(request, `/recordings/${rec!.id}/annotations?source=algorithm`);
  expect(algo).toHaveLength(1);
  expect(algo[0]).toMatchObject({ start_sample: modified, label: 'R_peak', lead: 'II' });
  expect(algo[0].provenance).toMatchObject({ original_start_sample: edgeStart, algorithm: 'scipy_pan_tompkins' });
  // reviewed reference annotations are unchanged
  const refAfter = (await apiGet<Ann[]>(request, `/recordings/${rec!.id}/annotations?source=reference`)).map(key).sort();
  expect(refAfter).toEqual(refBefore);

  // ---- 19. export ----------------------------------------------------------------
  await page.getByTestId('export-button').click();
  await page.getByTestId('export-name').fill('e2e-ludb3');
  await page.getByTestId('export-scope').selectOption('recording');
  await page.getByTestId('export-create').click();
  await expect(page.getByTestId('export-result')).toContainText('patient leakage check: passed');
  const version = (await page.getByTestId('export-version').textContent())!;
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByTestId('export-download').click()]);
  const zipPath = test.info().outputPath(`${version}.zip`);
  await download.saveAs(zipPath);

  // ---- 20. re-import (verify against DB, then into a new recording) ------------------
  await page.getByTestId('import-mode').selectOption('verify');
  await page.getByTestId('import-file').setInputFiles(zipPath);
  await expect(page.getByTestId('import-ok')).toHaveText('Round trip OK: sample positions and labels identical');
  await page.getByTestId('import-mode').selectOption('new_recording');
  await page.getByTestId('import-file').setInputFiles(zipPath);
  await expect(page.getByTestId('import-report')).toContainText('signal identical: true');
  await expect(page.getByTestId('import-ok')).toHaveText('Round trip OK: sample positions and labels identical');

  // ---- 21. positions and labels unchanged ---------------------------------------------
  const original = (await apiGet<Ann[]>(request, `/recordings/${rec!.id}/annotations`)).map(key).sort();
  await page.getByTestId('open-imported').click();
  await expect(page.getByTestId('status-bar')).toContainText(/Loaded .*: 5000 samples @ 500 Hz, 12 leads/);
  const newId = new URL(page.url()).searchParams.get('recording')!;
  expect(newId).not.toBe(rec!.id);
  const imported = (await apiGet<Ann[]>(request, `/recordings/${newId}/annotations`)).map(key).sort();
  expect(imported).toEqual(original);
  await setView(page, VIEW[0], VIEW[1]);
  for (const a of saved) {
    const row = page.getByTestId(`tier-row-${a.tier}`);
    await expect(row.locator(`[data-label="${a.label}"][data-start="${a.start_sample}"][data-end="${a.end_sample ?? ''}"]`)).toHaveCount(1);
  }

  expect(dialogs, 'no unexpected confirm dialogs').toEqual([]);
});
