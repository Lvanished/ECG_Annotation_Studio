import { useEffect, useMemo, useRef, useState } from 'react';
import type { Ontology, Prediction } from '../api/types';
import { cachedChunks, useChunks, useQueryClient } from '../api/queries';
import { drawWaveform, readoutAt, type Segment } from '../lib/draw';
import { bucketFor, chunkIndices, chunkSpan } from '../lib/lod';
import { tierAccepts } from '../lib/annotations';
import { formatTime, sampleToX, xToSample } from '../lib/viewport';
import { useSize } from '../hooks/useSize';
import { useEditor } from '../store/editor';
import { addAnnotation } from '../store/actions';
import { GUTTER } from './layout';

interface Props {
  onto: Ontology;
  predictions: Prediction[];
}

type Drag = { x0: number; s0: number; s1: number; moved: boolean; button: number; v0?: { start: number; end: number } };

export function WaveformView({ onto, predictions }: Props) {
  const rec = useEditor((s) => s.recording)!;
  const view = useEditor((s) => s.view);
  const leads = useEditor((s) => s.displayLeads);
  const mvPerStrip = useEditor((s) => s.mvPerStrip);
  const cursor = useEditor((s) => s.cursor);
  const selection = useEditor((s) => s.selection);
  const working = useEditor((s) => s.working);
  const selectedId = useEditor((s) => s.selectedId);
  const hiddenTiers = useEditor((s) => s.hiddenTiers);
  const annotationLead = useEditor((s) => s.annotationLead);
  const tool = useEditor((s) => s.tool);
  const activeTier = useEditor((s) => s.activeTier);
  const predictionEdits = useEditor((s) => s.predictionEdits);
  const selectedPredictionId = useEditor((s) => s.selectedPredictionId);
  const st = useEditor.getState;

  const wrapRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrap = useSize(wrapRef);
  const plot = useSize(plotRef);
  const width = Math.max(10, Math.floor(plot.width));
  const stripH = Math.max(56, Math.min(240, Math.floor((wrap.height || 400) / Math.max(1, leads.length))));
  const totalH = stripH * leads.length;
  const [drag, setDrag] = useState<Drag | null>(null);
  const [hover, setHover] = useState<number | null>(null);

  const span = view.end - view.start;
  const bucket = bucketFor(span, width);
  const chunkQs = useChunks(rec, leads, view.start, view.end, bucket);
  const qc = useQueryClient();
  const tiers = useMemo(() => Object.fromEntries(onto.tiers.map((t) => [t.name, t])), [onto.tiers]);
  const anns = useMemo(() => Object.values(working), [working]);

  const segments: Segment[] = useMemo(() => {
    const loaded = new Map<number, Segment>();
    for (const q of chunkQs) if (q.data) loaded.set(q.data.index, { chunk: q.data, from: q.data.start, to: q.data.end });
    const need = chunkIndices(view.start, view.end, bucket, rec.n_samples, 0);
    const out: Segment[] = [];
    let fallback: ReturnType<typeof cachedChunks> | null = null;
    for (const i of need) {
      const seg = loaded.get(i);
      if (seg) {
        out.push(seg);
        continue;
      }
      fallback ??= cachedChunks(qc, rec.id, leads);
      const from = i * chunkSpan(bucket);
      const to = Math.min(rec.n_samples, from + chunkSpan(bucket));
      const cover = fallback
        .filter((c) => c.start < to && c.end > from)
        .sort((a, b) => Math.abs(Math.log2(a.bucket / bucket)) - Math.abs(Math.log2(b.bucket / bucket)));
      for (const c of cover) out.push({ chunk: c, from: Math.max(from, c.start), to: Math.min(to, c.end) });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chunkQs.map((q) => q.dataUpdatedAt).join(','), view.start, view.end, bucket, rec.id, leads.join(',')]);
  const loading = chunkQs.some((q) => q.isFetching);

  const preview: [number, number] | null =
    drag && drag.moved && drag.button === 0 ? [Math.min(drag.s0, drag.s1), Math.max(drag.s0, drag.s1)] : null;
  const previewColor = tool === 'annotate' ? tiers[activeTier]?.color ?? '#2563eb' : '#2563eb';

  useEffect(() => {
    const c = canvasRef.current;
    if (!c || !width) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = Math.round(width * dpr);
    c.height = Math.round(totalH * dpr);
    c.style.width = `${width}px`;
    c.style.height = `${totalH}px`;
    const ctx = c.getContext('2d');
    if (!ctx) return;
    const raf = requestAnimationFrame(() =>
      drawWaveform(
        ctx,
        {
          width,
          stripH,
          leads,
          view,
          fs: rec.fs,
          mvPerStrip,
          segments,
          annotations: anns,
          tiers,
          hiddenTiers,
          selectedId,
          predictions,
          predictionEdits,
          selectedPredictionId,
          cursor,
          selection,
          preview: tool === 'select' && preview ? null : preview,
          previewColor,
          annotationLead,
        },
        dpr,
      ),
    );
    return () => cancelAnimationFrame(raf);
  }, [width, totalH, stripH, leads, view, rec.fs, mvPerStrip, segments, anns, tiers, hiddenTiers, selectedId, predictions,
    predictionEdits, selectedPredictionId, cursor, selection, preview, previewColor, annotationLead, tool]);

  // wheel zoom (non-passive listener so we can preventDefault)
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const v = st().view;
      const rect = el.getBoundingClientRect();
      if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
        const d = e.shiftKey ? e.deltaY : e.deltaX;
        st().pan(Math.sign(d) * Math.max(1, Math.round((v.end - v.start) * 0.1)));
        return;
      }
      const anchor = xToSample(e.clientX - rect.left, v, rect.width);
      st().zoom(e.deltaY < 0 ? 1 / 1.25 : 1.25, anchor);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [st]);

  const sampleAt = (clientX: number) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    const s = xToSample(clientX - rect.left, st().view, rect.width);
    return Math.max(0, Math.min(rec.n_samples, s));
  };
  const stripAt = (clientY: number) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    return Math.max(0, Math.min(leads.length - 1, Math.floor((clientY - rect.top) / stripH)));
  };

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    const s = sampleAt(e.clientX);
    setDrag({ x0: e.clientX, s0: s, s1: s, moved: false, button: e.button, v0: { ...st().view } });
  };
  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const s = sampleAt(e.clientX);
    setHover(s);
    if (!drag) return;
    const moved = drag.moved || Math.abs(e.clientX - drag.x0) > 3;
    if (drag.button === 1 && drag.v0) {
      const rect = canvasRef.current!.getBoundingClientRect();
      const dx = e.clientX - drag.x0;
      const ds = Math.round((-dx / rect.width) * (drag.v0.end - drag.v0.start));
      st().setView(drag.v0.start + ds, drag.v0.end + ds);
    }
    setDrag({ ...drag, s1: s, moved });
  };
  const onPointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drag) return;
    const s = sampleAt(e.clientX);
    const d = { ...drag, s1: s };
    setDrag(null);
    if (d.button !== 0) return;
    const a = Math.min(d.s0, d.s1);
    const b = Math.max(d.s0, d.s1);
    const tier = tiers[st().activeTier];
    if (d.moved && b > a) {
      if (tool === 'annotate' && tierAccepts(tier, 'interval')) {
        addAnnotation(onto, tier.name, a, b);
      } else {
        st().setSelection([a, b]);
        st().setCursor(a);
      }
      return;
    }
    const point = Math.min(rec.n_samples - 1, d.s0);
    st().setCursor(point);
    st().setSelection(null);
    if (tool === 'annotate' && tierAccepts(tier, 'point')) {
      addAnnotation(onto, tier.name, point, null);
      return;
    }
    // select a nearby point annotation on this strip
    const lead = leads[stripAt(e.clientY)];
    const rect = canvasRef.current!.getBoundingClientRect();
    const x = e.clientX - rect.left;
    let best: string | null = null;
    let bestD = 6;
    for (const ann of anns) {
      if (ann.kind !== 'point' || hiddenTiers.includes(ann.tier)) continue;
      if (ann.lead !== null && ann.lead !== lead) continue;
      const dx = Math.abs(sampleToX(ann.start_sample, st().view, rect.width) - x);
      if (dx < bestD) {
        bestD = dx;
        best = ann.id;
      }
    }
    if (best) st().select(best);
  };

  const readout = hover ?? cursor;
  const fs = rec.fs;
  return (
    <div className="flex min-h-[220px] flex-1 flex-col">
      <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-2 py-0.5 font-mono text-2xs text-slate-600">
        <span data-testid="view-range">
          view [{view.start}, {view.end}) · {formatTime(view.start / fs)} – {formatTime(view.end / fs)} · span{' '}
          {((span / fs) * 1000).toFixed(0)} ms
        </span>
        <span data-testid="cursor-readout">
          {readout !== null
            ? `${hover !== null ? 'mouse' : 'cursor'} sample ${readout} · ${formatTime(readout / fs)}` +
              leads
                .slice(0, 3)
                .map((l) => {
                  const v = readoutAt(segments, l, readout);
                  return v === null ? '' : ` · ${l} ${v}`;
                })
                .join('')
            : 'no cursor'}
        </span>
        {selection && (
          <span>
            selection [{selection[0]}, {selection[1]}) = {(((selection[1] - selection[0]) / fs) * 1000).toFixed(1)} ms
          </span>
        )}
        <span className="ml-auto">
          {bucket === 1 ? 'raw samples' : `min/max envelope · ${bucket} samples/bucket`}
          {loading ? ' · loading…' : ''}
        </span>
      </div>
      <div ref={wrapRef} className="stable-gutter relative min-h-0 flex-1 overflow-y-auto overflow-x-hidden bg-white">
        <div className="flex" style={{ height: totalH }}>
          <div className="shrink-0 border-r border-slate-200 bg-slate-50" style={{ width: GUTTER }}>
            {leads.map((l) => (
              <div
                key={l}
                className={`relative flex items-start justify-between border-b border-slate-200 px-2 pt-1 ${l === annotationLead ? 'border-l-4 border-l-blue-500 bg-blue-50/60' : ''}`}
                style={{ height: stripH }}
              >
                <button
                  className="font-mono text-xs font-bold text-slate-700 hover:text-blue-700"
                  title="Set as annotation lead"
                  data-testid={`lead-label-${l}`}
                  onClick={() => st().setAnnotationLead(l)}
                >
                  {l}
                </button>
                <div className="flex flex-col items-end text-2xs text-slate-500">
                  <span>{rec.units[rec.leads.indexOf(l)] ?? 'mV'}</span>
                  <span
                    className="mt-1 w-1 bg-slate-700"
                    style={{ height: Math.min(stripH - 18, stripH / mvPerStrip) }}
                    title="1 mV scale bar"
                  />
                  <span>1 mV</span>
                </div>
              </div>
            ))}
          </div>
          <div ref={plotRef} className="relative min-w-0 flex-1">
            <canvas
              ref={canvasRef}
              data-testid="waveform-canvas"
              className={tool === 'annotate' ? 'cursor-crosshair' : 'cursor-text'}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerLeave={() => setHover(null)}
              onContextMenu={(e) => e.preventDefault()}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
