/**
 * Pre-annotation pipeline and analysis panels on the real LUDB record 4:
 * R-peak run -> beat segmentation -> accept all in view, experimental
 * delineation, signal-quality / validation / history tabs. Every displayed
 * number is compared with the API it comes from.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

interface Ann { id: string; tier: string; label: string; source: string; revision: number; start_sample: number }
interface Pred { start_sample: number; end_sample: number | null; label: string; status: string }
interface Run { id: string; algorithm: string; experimental: boolean; predictions: Pred[] }

async function get<T>(request: APIRequestContext, path: string): Promise<T> {
  const res = await request.get(`/api${path}`);
  expect(res.ok(), `${path} -> ${res.status()}`).toBeTruthy();
  return (await res.json()) as T;
}

async function cleanup(request: APIRequestContext, recId: string) {
  for (const a of await get<Ann[]>(request, `/recordings/${recId}/annotations`)) {
    if (a.source === 'reference') continue;
    expect((await request.delete(`/api/annotations/${a.id}?revision=${a.revision}&confirm_reviewed_change=true`)).ok()).toBeTruthy();
  }
  for (const r of await get<Run[]>(request, `/recordings/${recId}/prediction-runs`))
    expect((await request.delete(`/api/prediction-runs/${r.id}`)).ok()).toBeTruthy();
}

async function setView(page: Page, a: number, b: number) {
  await page.getByTestId('view-start').fill(String(a));
  await page.getByTestId('view-end').fill(String(b));
  await page.getByTestId('view-go').click();
  await expect(page.getByTestId('view-range')).toContainText(`view [${a}, ${b})`);
}

test('pre-annotation pipeline, accept-in-view and analysis tabs', async ({ page, request }) => {
  const rec = (await get<{ id: string; dataset_id: string; name: string }[]>(request, '/recordings'))
    .find((r) => r.dataset_id === 'ludb' && r.name === '4')!;
  expect(rec, 'ludb/4 must be registered (bundled sample)').toBeTruthy();
  await cleanup(request, rec.id);

  await page.goto(`/?recording=${rec.id}`);
  await expect(page.getByTestId('status-bar')).toContainText('Loaded ludb/4');
  await expect(page.getByTestId('dataset-citation')).toContainText('https://doi.org/10.13026/eegm-h675');

  // R peaks -> beat regions (explicit RR-fraction boundaries)
  await page.getByTestId('auto-menu').click();
  await page.getByTestId('detect-all').click();
  await expect(page.getByTestId('status-bar')).toContainText(/scipy_pan_tompkins@[\d.]+: \d+ predictions on II/);
  await page.getByTestId('auto-menu').click();
  await page.getByTestId('segment-beats').click();
  await expect(page.getByTestId('status-bar')).toContainText(/rr_fraction_beat_segmentation@1\.0\.0: \d+ predictions/);

  // experimental delineation is labelled as such
  await page.getByTestId('auto-menu').click();
  await page.getByTestId('delineate-view').click();
  await expect(page.getByTestId('status-bar')).toContainText('(EXPERIMENTAL)');
  const runs = await get<Run[]>(request, `/recordings/${rec.id}/prediction-runs`);
  expect(runs.map((r) => r.algorithm)).toEqual(['scipy_pan_tompkins', 'rr_fraction_beat_segmentation', expect.stringContaining('delineat')]);
  expect(runs[2].experimental).toBe(true);
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('runs-list')).toContainText('experimental');

  // accept every beat region starting inside the view
  const seg = runs[1];
  await setView(page, 0, 2000);
  const expected = seg.predictions.filter((p) => p.start_sample >= 0 && p.start_sample < 2000);
  expect(expected.length).toBeGreaterThan(0);
  await page.getByTestId(`accept-range-${seg.id}`).click();
  await expect(page.getByTestId('status-bar')).toContainText(`Accepted ${expected.length} prediction(s) in [0, 2000); 0 skipped`);
  const accepted = (await get<Ann[]>(request, `/recordings/${rec.id}/annotations?source=algorithm`)).filter((a) => a.tier === 'Beat');
  expect(accepted.map((a) => a.start_sample).sort((a, b) => a - b)).toEqual(expected.map((p) => p.start_sample).sort((a, b) => a - b));
  await expect(page.getByTestId('tier-row-Beat').locator('[data-label="beat_region"]')).toHaveCount(expected.length);

  // signal quality: the table shows the API values for the visible window
  await page.getByTestId('tab-quality').click();
  const q = await get<{ leads: Record<string, Record<string, number>> }>(request,
    `/recordings/${rec.id}/quality?start=0&end=2000&leads=${encodeURIComponent('I,II,III,aVR,aVL,aVF,V1,V2,V3,V4,V5,V6')}`);
  const panel = page.getByTestId('analysis-panel');
  for (const lead of ['I', 'II', 'V6']) {
    const row = panel.locator('tr', { has: page.locator('td.font-bold', { hasText: new RegExp(`^${lead}$`) }) });
    await expect(row).toContainText(q.leads[lead].amplitude_range_mv.toFixed(3));
    await expect(row).toContainText(q.leads[lead].flatline_fraction.toFixed(3));
  }

  // validation of saved annotations
  await page.getByTestId('tab-validation').click();
  const v = await get<{ n_issues: number }>(request, `/recordings/${rec.id}/validate`);
  await expect(panel).toContainText(`${v.n_issues} issue(s) in saved annotations`);

  // the (append-only) recording history has one create per accepted prediction, newest first
  const ids = new Set(accepted.map((a) => a.id));
  const hist = await get<{ annotation_id: string; actor: string; operation: string }[]>(request, `/recordings/${rec.id}/history?limit=200`);
  expect(hist.filter((h) => ids.has(h.annotation_id)).map((h) => `${h.operation}/${h.actor}`))
    .toEqual(Array(expected.length).fill('create/prediction-review'));
  await page.getByTestId('tab-history').click();
  const rows = panel.locator('tr');
  await expect(rows).toHaveCount(hist.length);
  for (let i = 0; i < expected.length; i++) await expect(rows.nth(i)).toContainText('prediction-review');

  // discard the delineation run from the UI; accepted annotations stay
  await page.getByTestId(`discard-run-${runs[2].id}`).click();
  await expect(page.getByTestId(`discard-run-${runs[2].id}`)).toHaveCount(0);
  expect((await get<Run[]>(request, `/recordings/${rec.id}/prediction-runs`)).length).toBe(2);

  await cleanup(request, rec.id);
});
