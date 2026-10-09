import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TierPanel } from './TierPanel';
import { PropertiesPanel } from './PropertiesPanel';
import { useEditor } from '../store/editor';
import { drawWaveform } from '../lib/draw';
import { ann, ONTO, REC, resetEditor } from '../test/fixtures';

const st = useEditor.getState;

// Every [data-track] is laid out as 1000 px wide starting at x = 0.
function layoutTracks() {
  Element.prototype.getBoundingClientRect = function () {
    return { left: 0, top: 0, width: 1000, height: 30, right: 1000, bottom: 30, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
  };
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  layoutTracks();
  vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { status: 200 })));
  resetEditor([
    ann('r1', { start_sample: 1000 }),
    ann('q1', { tier: 'QRS Complex', label: 'QRS_complex', kind: 'interval', start_sample: 980, end_sample: 1030 }),
  ]);
  st().setView(0, 2000); // 2 samples per pixel
});
afterEach(() => vi.unstubAllGlobals());

function drag(el: Element, fromX: number, toX: number) {
  fireEvent.pointerDown(el, { clientX: fromX, pointerId: 1, buttons: 1 });
  act(() => {
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: (fromX + toX) / 2 }));
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: toX }));
    window.dispatchEvent(new MouseEvent('pointerup', { clientX: toX }));
  });
}

describe('TierPanel', () => {
  it('renders annotations of every visible tier at integer sample positions', () => {
    wrap(<TierPanel onto={ONTO} predictions={[]} />);
    expect(screen.getByTestId('ann-r1')).toHaveAttribute('data-start', '1000');
    expect(screen.getByTestId('ann-q1')).toHaveAttribute('data-end', '1030');
    expect(screen.getByTestId('ann-r1').style.left).toBe('500px');
  });

  it('drags a point by whole samples and undoes it in one step', () => {
    wrap(<TierPanel onto={ONTO} predictions={[]} />);
    drag(screen.getByTestId('ann-r1'), 500, 510); // +10 px = +20 samples
    expect(st().working.r1.start_sample).toBe(1020);
    expect(screen.getByTestId('ann-r1')).toHaveAttribute('data-start', '1020');
    expect(st().undoStack).toHaveLength(1);
    act(() => st().undo());
    expect(st().working.r1.start_sample).toBe(1000);
  });

  it('drags interval boundaries independently and keeps start < end', () => {
    wrap(<TierPanel onto={ONTO} predictions={[]} />);
    const el = screen.getByTestId('ann-q1');
    drag(el.querySelector('[data-handle="end"]')!, 515, 520);
    expect(st().working.q1).toMatchObject({ start_sample: 980, end_sample: 1040 });
    drag(el.querySelector('[data-handle="start"]')!, 490, 900);
    expect(st().working.q1).toMatchObject({ start_sample: 1039, end_sample: 1040 });
  });

  it('hides and restores a tier', () => {
    wrap(<TierPanel onto={ONTO} predictions={[]} />);
    fireEvent.click(screen.getByTestId('hide-tier-QRS Complex'));
    expect(screen.queryByTestId('tier-row-QRS Complex')).toBeNull();
    fireEvent.click(screen.getByTestId('show-tier-QRS Complex'));
    expect(screen.getByTestId('tier-row-QRS Complex')).toBeInTheDocument();
  });

  it('double-click on a point tier creates a point at that sample', () => {
    wrap(<TierPanel onto={ONTO} predictions={[]} />);
    const track = screen.getByTestId('tier-row-Fiducial Points').querySelector('[data-track]')!;
    fireEvent.doubleClick(track, { clientX: 700 });
    const created = Object.values(st().working).find((a) => a.start_sample === 1400);
    expect(created).toMatchObject({ label: 'R_peak', lead: 'II', kind: 'point', source: 'manual' });
  });
});

describe('PropertiesPanel', () => {
  it('edits label, boundaries and morphology attribute of the selected annotation', () => {
    act(() => st().select('q1'));
    wrap(<PropertiesPanel onto={ONTO} runs={[]} datasets={[]} />);
    const start = screen.getByTestId('prop-start');
    fireEvent.change(start, { target: { value: '985' } });
    fireEvent.blur(start);
    expect(st().working.q1.start_sample).toBe(985);
    fireEvent.change(screen.getByTestId('attr-morphology'), { target: { value: 'notched' } });
    expect(st().working.q1.attributes).toEqual({ morphology: 'notched' });
    const end = screen.getByTestId('prop-end');
    fireEvent.change(end, { target: { value: '900' } }); // before start: rejected
    fireEvent.blur(end);
    expect(st().working.q1.end_sample).toBe(1030);
  });

  it('deletes the selected annotation', () => {
    act(() => st().select('r1'));
    wrap(<PropertiesPanel onto={ONTO} runs={[]} datasets={[]} />);
    fireEvent.click(screen.getByTestId('prop-delete'));
    expect(st().working.r1).toBeUndefined();
    expect(st().selectedId).toBeNull();
  });
});

describe('drawWaveform', () => {
  it('draws raw samples for every displayed lead and envelopes when decimated', () => {
    const calls = (globalThis as unknown as { __canvasCalls: string[] }).__canvasCalls;
    const ctx = document.createElement('canvas').getContext('2d')!;
    const ramp = Array.from({ length: 1024 }, (_, i) => i / 1024);
    const base = {
      width: 1000,
      stripH: 100,
      leads: ['I', 'II'],
      view: { start: 0, end: 1000 },
      fs: REC.fs,
      mvPerStrip: 3,
      annotations: [],
      tiers: {},
      hiddenTiers: [],
      selectedId: null,
      predictions: [],
      predictionEdits: {},
      selectedPredictionId: null,
      cursor: null,
      selection: null,
      preview: null,
      previewColor: '#000',
      annotationLead: 'II',
    };
    calls.length = 0;
    drawWaveform(ctx, {
      ...base,
      segments: [{ chunk: { start: 0, end: 1024, bucket: 1, index: 0, fs: 500, leads: { I: { values: ramp }, II: { values: ramp } } }, from: 0, to: 1024 }],
    });
    const raw = calls.filter((c) => c.startsWith('lineTo')).length;
    expect(raw).toBeGreaterThan(2 * 990);
    calls.length = 0;
    drawWaveform(ctx, {
      ...base,
      view: { start: 0, end: 4096 },
      segments: [{ chunk: { start: 0, end: 4096, bucket: 4, index: 0, fs: 500, leads: { I: { min: ramp, max: ramp }, II: { min: ramp, max: ramp } } }, from: 0, to: 4096 }],
    });
    expect(calls.filter((c) => c.startsWith('lineTo')).length).toBeGreaterThan(2 * 1000);
  });
});
