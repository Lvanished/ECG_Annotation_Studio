import { describe, expect, it } from 'vitest';
import { centerOn, clampView, gridSpacing, pan, sampleToX, xToSample, zoomAt } from './viewport';
import { bucketFor, chunkIndices, chunkSpan } from './lod';
import { beatAnchors, diffOps, nextAnchor, overlapConflict, reviewedTouched, labelsForTier } from './annotations';
import { ann, ONTO } from '../test/fixtures';

describe('viewport', () => {
  it('clamps to recording bounds and minimum span', () => {
    expect(clampView(-50, 100, 1000)).toEqual({ start: 0, end: 150 });
    expect(clampView(990, 1100, 1000)).toEqual({ start: 890, end: 1000 });
    expect(clampView(10, 12, 1000)).toEqual({ start: 10, end: 30 });
    expect(clampView(0, 5000, 1000)).toEqual({ start: 0, end: 1000 });
  });

  it('maps samples to pixels and back exactly on integer boundaries', () => {
    const v = { start: 1000, end: 2000 };
    expect(sampleToX(1500, v, 500)).toBe(250);
    for (const s of [1000, 1234, 1999, 2000]) expect(xToSample(sampleToX(s, v, 500), v, 500)).toBe(s);
  });

  it('zoom keeps the anchor within one sample of its pixel and stays integer', () => {
    let v = { start: 0, end: 10000 };
    const anchor = 3700;
    for (let i = 0; i < 8; i++) {
      const x = sampleToX(anchor, v, 1000);
      v = zoomAt(v, anchor, 0.5, 100000);
      expect(Math.abs(sampleToX(anchor, v, 1000) - x)).toBeLessThanOrEqual(1000 / (v.end - v.start));
    }
    for (let i = 0; i < 8; i++) v = zoomAt(v, anchor, 2, 100000);
    expect(Math.abs(v.end - v.start - 10000)).toBeLessThan(300); // integer span rounding only
    expect(Number.isInteger(v.start) && Number.isInteger(v.end)).toBe(true);
  });

  it('pans and centres within bounds', () => {
    expect(pan({ start: 0, end: 100 }, -50, 1000)).toEqual({ start: 0, end: 100 });
    expect(pan({ start: 0, end: 100 }, 950, 1000)).toEqual({ start: 900, end: 1000 });
    expect(centerOn({ start: 0, end: 100 }, 500, 1000)).toEqual({ start: 450, end: 550 });
  });

  it('chooses ECG paper grid at 40/200 ms when zoomed in', () => {
    expect(gridSpacing(250, 5)).toEqual({ minor: 0.04, major: 0.2 });
    expect(gridSpacing(10, 5).minor).toBeGreaterThan(0.04);
  });
});

describe('level of detail', () => {
  it('uses raw samples when zoomed in and power-of-two buckets otherwise', () => {
    expect(bucketFor(500, 1000)).toBe(1);
    expect(bucketFor(650000, 1000)).toBe(512);
    expect(bucketFor(3000, 1000)).toBe(2);
  });

  it('lists chunk indices covering the view with prefetch', () => {
    expect(chunkSpan(4)).toBe(4096);
    expect(chunkIndices(0, 1024, 1, 5000, 0)).toEqual([0]);
    expect(chunkIndices(1000, 2100, 1, 5000, 0)).toEqual([0, 1, 2]);
    expect(chunkIndices(1000, 2100, 1, 5000, 1)).toEqual([0, 1, 2, 3]);
    expect(chunkIndices(4000, 5000, 1, 5000, 3)).toEqual([0, 1, 2, 3, 4]);
  });
});

describe('annotation document diff', () => {
  const a = ann('a', { start_sample: 100 });
  const b = ann('b', { start_sample: 200, review_status: 'reviewed' });

  it('produces create, update and delete operations with revisions', () => {
    const server = { a, b };
    const working = { a: { ...a, start_sample: 105 }, 'tmp-1': ann('tmp-1', { start_sample: 300, revision: 0 }) };
    const ops = diffOps(server, working);
    expect(ops).toHaveLength(3);
    expect(ops.find((o) => o.op === 'update')).toMatchObject({ id: 'a', revision: 1, data: { start_sample: 105 } });
    expect(ops.find((o) => o.op === 'create')).toMatchObject({ client_id: 'tmp-1', data: { start_sample: 300, source: 'manual' } });
    expect(ops.find((o) => o.op === 'delete')).toMatchObject({ id: 'b', revision: 1 });
    expect(reviewedTouched(server, ops)).toEqual(['b']);
  });

  it('produces no ops when the working copy equals the server', () => {
    expect(diffOps({ a }, { a: { ...a, attributes: {} } })).toEqual([]);
  });
});

describe('overlap policy and labels', () => {
  const qrs = ONTO.tiers.find((t) => t.name === 'QRS Complex');
  const existing = ann('q1', { tier: 'QRS Complex', label: 'QRS_complex', kind: 'interval', start_sample: 100, end_sample: 150 });

  it('detects overlap within a lead on forbid_same_lead tiers (half-open)', () => {
    const touching = ann('q2', { tier: 'QRS Complex', label: 'QRS_complex', kind: 'interval', start_sample: 150, end_sample: 190 });
    const overlapping = { ...touching, start_sample: 149 };
    const otherLead = { ...overlapping, lead: 'I' };
    expect(overlapConflict([existing], qrs, touching)).toBeNull();
    expect(overlapConflict([existing], qrs, overlapping)?.id).toBe('q1');
    expect(overlapConflict([existing], qrs, otherLead)).toBeNull();
  });

  it('lists only labels valid for the tier and geometry', () => {
    const fid = ONTO.tiers.find((t) => t.name === 'Fiducial Points');
    expect(labelsForTier(ONTO.labels, fid, 'point').map((l) => l.code)).toEqual(['R_peak', 'P_peak']);
    expect(labelsForTier(ONTO.labels, fid, 'interval')).toEqual([]);
  });
});

describe('beat navigation', () => {
  it('uses R peaks on the lead (or global) and falls back to QRS centres', () => {
    const anns = [
      ann('r1', { start_sample: 400 }),
      ann('r2', { start_sample: 900, lead: null }),
      ann('r3', { start_sample: 1300, lead: 'I' }),
    ];
    expect(beatAnchors(anns, [], 'II')).toEqual([400, 900]);
    const qrs = [ann('q', { tier: 'QRS Complex', label: 'QRS_complex', kind: 'interval', start_sample: 100, end_sample: 141 })];
    expect(beatAnchors(qrs, [], 'II')).toEqual([120]);
    expect(nextAnchor([400, 900], 400, 1)).toBe(900);
    expect(nextAnchor([400, 900], 400, -1)).toBeNull();
    expect(nextAnchor([400, 900], 1000, -1)).toBe(900);
  });
});
