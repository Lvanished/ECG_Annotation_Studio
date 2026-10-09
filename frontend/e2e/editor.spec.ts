/**
 * Editor behaviour beyond the acceptance workflow, on real PhysioNet records:
 * keyboard shortcuts, undo/redo, overlap policy, reviewed-annotation protection,
 * beat navigation, measurements traced to reference annotations, custom tiers,
 * tier visibility, and min/max envelope rendering of a 30-minute MIT-BIH record.
 *
 * Uses LUDB record 2, whose last beat (R near sample 4689, lead II) has no
 * reference annotations. Non-reference annotations left on ludb/2 by earlier
 * runs and the custom tier created here are removed via the API.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

interface Ann {
  id: string;
  tier: string;
  label: string;
  lead: string | null;
  start_sample: number;
  end_sample: number | null;
  source: string;
  review_status: string;
  revision: number;
}
interface Tier {
  id: string;
  name: string;
  order: number;
  is_custom: boolean;
}

const get = async <T,>(r: APIRequestContext, p: string): Promise<T> => {
  const res = await r.get(`/api${p}`);
  expect(res.ok(), `${p} -> ${res.status()}`).toBeTruthy();
  return (await res.json()) as T;
};

async function viewRange(page: Page): Promise<[number, number]> {
  const m = /view \[(\d+), (\d+)\)/.exec((await page.getByTestId('view-range').textContent()) ?? '');
  return [Number(m![1]), Number(m![2])];
}

async function setView(page: Page, a: number, b: number) {
  await page.getByTestId('view-start').fill(String(a));
  await page.getByTestId('view-end').fill(String(b));
  await page.getByTestId('view-go').click();
  await expect(page.getByTestId('view-range')).toContainText(`view [${a}, ${b})`);
  await page.getByTestId('waveform-canvas').hover({ position: { x: 2, y: 2 } });
}

async function xy(page: Page, s: number) {
  const box = (await page.getByTestId('waveform-canvas').boundingBox())!;
  const [a, b] = await viewRange(page);
  return { x: box.x + ((s - a) / (b - a)) * box.width, y: box.y + 30 };
}

async function dragCanvas(page: Page, s0: number, s1: number) {
  const p0 = await xy(page, s0);
  const p1 = await xy(page, s1);
  await page.mouse.move(p0.x, p0.y);
  await page.mouse.down();
  await page.mouse.move(p1.x, p1.y, { steps: 6 });
  await page.mouse.up();
}

async function cleanup(request: APIRequestContext, recId: string) {
  for (const a of await get<Ann[]>(request, `/recordings/${recId}/annotations`)) {
    if (a.source === 'reference') continue;
    expect((await request.delete(`/api/annotations/${a.id}?revision=${a.revision}&confirm_reviewed_change=true`)).ok()).toBeTruthy();
  }
  for (const t of await get<Tier[]>(request, '/tiers')) {
    if (t.is_custom && t.name.startsWith('E2E ')) await request.delete(`/api/tiers/${t.id}`);
  }
}

test('editor: shortcuts, undo/redo, overlap, reviewed protection, navigation, measurements, custom tier', async ({ page, request }) => {
  const recs = await get<{ id: string; dataset_id: string; name: string }[]>(request, '/recordings');
  const rec = recs.find((r) => r.dataset_id === 'ludb' && r.name === '2')!;
  expect(rec).toBeTruthy();
  await cleanup(request, rec.id);
  const tiers = (await get<Tier[]>(request, '/tiers')).sort((a, b) => a.order - b.order);
  const keyFor = (name: string) => String(tiers.findIndex((t) => t.name === name) + 1);
  const dialogs: string[] = [];
  const mod = process.platform === 'darwin' ? 'Meta' : 'Control';

  // deep link restores the recording
  await page.goto(`/?recording=${rec.id}`);
  await expect(page.getByTestId('status-bar')).toContainText('Loaded ludb/2');
  await page.getByTestId('leads-button').click();
  await page.getByTestId('leads-single').click();
  await page.mouse.move(5, 600);
  await expect(page.locator('[data-testid^="lead-label-"]')).toHaveCount(1);
  await setView(page, 4450, 4950);

  // --- point creation with keyboard tool/tier selection -----------------------
  await page.keyboard.press('a');
  await page.keyboard.press(keyFor('Fiducial Points'));
  await expect(page.getByTestId('active-tier')).toHaveValue('Fiducial Points');
  const r = await xy(page, 4689);
  await page.mouse.click(r.x, r.y);
  const fid = page.getByTestId('tier-row-Fiducial Points');
  const rEl = fid.locator('[data-label="R_peak"]');
  await expect(rEl).toHaveCount(1);
  const rId = ((await rEl.getAttribute('data-testid')) ?? '').slice(4);
  const r0 = Number(await rEl.getAttribute('data-start'));
  expect(Math.abs(r0 - 4689)).toBeLessThanOrEqual(2);

  // --- delete / undo / redo via keyboard ---------------------------------------
  await page.keyboard.press('Delete');
  await expect(page.getByTestId(`ann-${rId}`)).toHaveCount(0);
  await page.keyboard.press(`${mod}+z`);
  await expect(page.getByTestId(`ann-${rId}`)).toHaveAttribute('data-start', String(r0));
  await page.keyboard.press(`${mod}+Shift+z`);
  await expect(page.getByTestId(`ann-${rId}`)).toHaveCount(0);
  await page.keyboard.press(`${mod}+y`);
  await expect(page.getByTestId(`ann-${rId}`)).toHaveCount(0);
  await page.keyboard.press(`${mod}+z`);
  await expect(page.getByTestId(`ann-${rId}`)).toHaveCount(1);

  // --- sample-precise nudging -------------------------------------------------------
  await page.getByTestId(`ann-${rId}`).click();
  await page.keyboard.press('Alt+ArrowRight');
  await expect(page.getByTestId(`ann-${rId}`)).toHaveAttribute('data-start', String(r0 + 1));
  await page.keyboard.press('Shift+Alt+ArrowRight');
  await expect(page.getByTestId(`ann-${rId}`)).toHaveAttribute('data-start', String(r0 + 11));
  await page.keyboard.press('Alt+ArrowLeft');
  const rFinal = r0 + 10;
  await expect(page.getByTestId(`ann-${rId}`)).toHaveAttribute('data-start', String(rFinal));

  // --- interval + overlap policy ----------------------------------------------------
  await page.keyboard.press('Escape');
  await page.keyboard.press(keyFor('QRS Complex'));
  await expect(page.getByTestId('active-tier')).toHaveValue('QRS Complex');
  await dragCanvas(page, 4664, 4712);
  const qrsRow = page.getByTestId('tier-row-QRS Complex');
  await expect(qrsRow.locator('[data-testid^="ann-"]')).toHaveCount(1);
  await dragCanvas(page, 4700, 4740);
  await expect(page.getByTestId('status-bar')).toContainText('Overlaps QRS_complex');
  await expect(qrsRow.locator('[data-testid^="ann-"]')).toHaveCount(1);
  const qEl = qrsRow.locator('[data-testid^="ann-"]');
  const qId = ((await qEl.getAttribute('data-testid')) ?? '').slice(4);

  // --- Ctrl+S ---------------------------------------------------------------------------
  await page.keyboard.press(`${mod}+s`);
  await expect(page.getByTestId('status-bar')).toContainText('Saved: 2 created, 0 updated, 0 deleted');
  // server ids replace temporary ids
  const savedQ = (await get<Ann[]>(request, `/recordings/${rec.id}/annotations?source=manual&tier=QRS%20Complex`))[0];
  const savedR = (await get<Ann[]>(request, `/recordings/${rec.id}/annotations?source=manual&tier=Fiducial%20Points`))[0];
  expect(savedR.start_sample).toBe(rFinal);
  expect(qId.startsWith('tmp-')).toBeTruthy();
  await expect(page.getByTestId(`ann-${savedQ.id}`)).toHaveCount(1);

  // --- reviewed annotations need explicit confirmation ------------------------------
  await page.getByTestId(`ann-${savedQ.id}`).click();
  await page.getByTestId('prop-review').selectOption('reviewed');
  await page.keyboard.press(`${mod}+s`);
  await expect(page.getByTestId('status-bar')).toContainText('Saved: 0 created, 1 updated');
  await page.getByTestId('prop-start').fill(String(savedQ.start_sample + 2));
  await page.getByTestId('prop-start').press('Enter');
  page.once('dialog', async (d) => {
    dialogs.push(d.message());
    await d.dismiss();
  });
  await page.getByTestId('save').click();
  await expect(page.getByTestId('status-bar')).toContainText('Save cancelled');
  expect((await get<Ann[]>(request, `/recordings/${rec.id}/annotations?source=manual&tier=QRS%20Complex`))[0].start_sample).toBe(savedQ.start_sample);
  page.once('dialog', async (d) => {
    dialogs.push(d.message());
    await d.accept();
  });
  await page.getByTestId('save').click();
  await expect(page.getByTestId('status-bar')).toContainText('Saved: 0 created, 1 updated');
  expect(dialogs).toHaveLength(2);
  expect(dialogs[0]).toContain('expert-reviewed');
  const q3 = (await get<Ann[]>(request, `/recordings/${rec.id}/annotations?source=manual&tier=QRS%20Complex`))[0];
  expect(q3).toMatchObject({ start_sample: savedQ.start_sample + 2, review_status: 'reviewed', revision: 3 });
  await expect(page.getByTestId('history-list').locator('li')).toHaveCount(3);

  // --- beat navigation ------------------------------------------------------------------
  await page.keyboard.press('Escape');
  await page.keyboard.press('v');
  const c = await xy(page, 4550);
  await page.mouse.click(c.x, c.y);
  await page.keyboard.press(']');
  let [a, b] = await viewRange(page);
  expect(Math.abs((a + b) / 2 - rFinal)).toBeLessThanOrEqual(1);
  const refR = (await get<Ann[]>(request, `/recordings/${rec.id}/annotations?source=reference`))
    .filter((x) => x.label === 'R_peak' && x.lead === 'II')
    .map((x) => x.start_sample)
    .sort((x, y) => x - y);
  const prevR = refR.filter((s) => s < rFinal).at(-1)!;
  await page.keyboard.press('[');
  [a, b] = await viewRange(page);
  expect(Math.abs((a + b) / 2 - prevR)).toBeLessThanOrEqual(1);

  // --- zoom keys and fit ----------------------------------------------------------------
  const span0 = b - a;
  await page.keyboard.press('+');
  [a, b] = await viewRange(page);
  expect(b - a).toBeLessThan(span0);
  await page.keyboard.press('-');
  await page.keyboard.press('-');
  [a, b] = await viewRange(page);
  expect(b - a).toBeGreaterThan(span0);
  await page.keyboard.press('f');
  await expect(page.getByTestId('view-range')).toContainText('view [0, 5000)');

  // --- measurements traced to the reference annotations of a fully delineated beat ------
  // (the last annotated LUDB beat has no T wave, so use the second-to-last one)
  const ref = await get<Ann[]>(request, `/recordings/${rec.id}/annotations?source=reference`);
  const mR = refR.filter((s) => s < prevR).at(-1)!;
  const qrs = ref.find((x) => x.tier === 'QRS Complex' && x.lead === 'II' && x.start_sample <= mR && x.end_sample! > mR)!;
  const pw = ref.filter((x) => x.tier === 'P Wave' && x.lead === 'II' && x.end_sample! <= qrs.start_sample).sort((x, y) => y.start_sample - x.start_sample)[0];
  const tw = ref.filter((x) => x.tier === 'T Wave' && x.lead === 'II' && x.start_sample >= qrs.end_sample! && x.start_sample < prevR).sort((x, y) => x.start_sample - y.start_sample)[0];
  expect(qrs && pw && tw).toBeTruthy();
  const prevprev = refR.filter((s) => s < mR).at(-1)!;
  await setView(page, mR - 600, mR + 600);
  const cc = await xy(page, mR);
  await page.mouse.click(cc.x, cc.y);
  await page.getByTestId('tab-measurements').click();
  const ms = (n: number) => ((n / 500) * 1000).toFixed(1);
  await expect(page.getByTestId('measure-RR')).toContainText(`${ms(mR - prevprev)} ms`);
  await expect(page.getByTestId('measure-RR')).toContainText(`${prevprev} → ${mR}`);
  await expect(page.getByTestId('measure-QRS duration')).toContainText(`${ms(qrs.end_sample! - qrs.start_sample)} ms`);
  await expect(page.getByTestId('measure-PR interval')).toContainText(`${ms(qrs.start_sample - pw.start_sample)} ms`);
  await expect(page.getByTestId('measure-QT interval')).toContainText(`${ms(tw.end_sample! - qrs.start_sample)} ms`);
  await expect(page.getByTestId('measure-ST deviation (J+60ms)')).toContainText('exp');
  // the manual edge beat has no T wave: QT must be N/A, not invented
  await setView(page, 4450, 4950);
  const ce = await xy(page, rFinal);
  await page.mouse.click(ce.x, ce.y);
  await expect(page.getByTestId('measure-QT interval')).toContainText('N/A');
  await expect(page.getByTestId('measure-QT interval')).toContainText('missing T wave end');

  // --- custom tier with free-text labels -----------------------------------------------
  const tierName = `E2E Artifact ${Date.now()}`;
  await page.getByTestId('new-tier').click();
  await page.getByTestId('tier-name-input').fill(tierName);
  await page.getByTestId('tier-create').click();
  await expect(page.getByTestId('status-bar')).toContainText(`Created tier "${tierName}"`);
  await expect(page.getByTestId('active-tier')).toHaveValue(tierName);
  await page.getByTestId('active-label-free').fill('lead_reversal_suspected');
  await page.getByTestId('tool-annotate').click();
  await dragCanvas(page, 4500, 4540);
  const custom = page.getByTestId(`tier-row-${tierName}`).locator('[data-label="lead_reversal_suspected"]');
  await expect(custom).toHaveCount(1);
  await page.keyboard.press(`${mod}+s`);
  await expect(page.getByTestId('status-bar')).toContainText('Saved: 1 created');
  const cust = await get<Ann[]>(request, `/recordings/${rec.id}/annotations?tier=${encodeURIComponent(tierName)}`);
  expect(cust).toHaveLength(1);
  expect(cust[0]).toMatchObject({ label: 'lead_reversal_suspected', lead: 'II', kind: 'interval' });

  // --- tier visibility and collapse --------------------------------------------------------
  await page.getByTestId('hide-tier-Morphology').click();
  await expect(page.getByTestId('tier-row-Morphology')).toHaveCount(0);
  await page.getByTestId('show-tier-Morphology').click();
  await expect(page.getByTestId('tier-row-Morphology')).toHaveCount(1);
  await page.getByTestId('tier-row-T Wave').getByTitle('Collapse/expand').click();
  await expect(page.getByTestId('tier-row-T Wave')).toHaveCSS('height', '12px');
  await page.getByTestId('tier-row-T Wave').getByTitle('Collapse/expand').click();
  await expect(page.getByTestId('tier-row-T Wave')).toHaveCSS('height', '30px');

  await cleanup(request, rec.id);
});

test('long MIT-BIH record: min/max envelope, chunked loading, wheel zoom to raw samples', async ({ page, request }) => {
  const recs = await get<{ id: string; dataset_id: string; name: string; n_samples: number }[]>(request, '/recordings');
  const rec = recs.find((r) => r.dataset_id === 'mitdb' && r.name === '100')!;
  expect(rec.n_samples).toBe(650000);
  await page.goto(`/?recording=${rec.id}`);
  await expect(page.getByTestId('status-bar')).toContainText('Loaded mitdb/100');
  await expect(page.locator('[data-testid^="lead-label-"]')).toHaveCount(2);
  await page.keyboard.press('f');
  await expect(page.getByTestId('view-range')).toContainText('view [0, 650000)');
  await expect(page.getByTestId('view-range').locator('xpath=..')).toContainText(/min\/max envelope · \d+ samples\/bucket/);
  await expect(page.getByTestId('view-range').locator('xpath=..')).not.toContainText('loading');
  const box = (await page.getByTestId('waveform-canvas').boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.5, box.y + 40);
  for (let i = 0; i < 30; i++) await page.mouse.wheel(0, -200); // 650000 * 0.8^30 ~ 800 samples
  await expect(page.getByTestId('view-range').locator('xpath=..')).toContainText('raw samples');
  const [a, b] = await viewRange(page);
  expect(b - a).toBeLessThan(2000);
  expect(a).toBeGreaterThan(250000);
  expect(b).toBeLessThan(400000);
  // the reference beat annotations of this window are shown
  await expect(page.getByTestId('tier-row-Beat').locator('[data-testid^="ann-"]').first()).toBeVisible();
  await expect(page.getByTestId('cursor-readout')).toContainText(/MLII -?\d+\.\d{3} mV/);
});
