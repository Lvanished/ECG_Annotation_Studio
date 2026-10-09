import type { Annotation, Chunk, Prediction, Tier } from '../api/types';
import { gridSpacing, sampleToX, type View } from './viewport';

export interface Segment {
  chunk: Chunk;
  from: number; // sample range of this segment to draw [from, to)
  to: number;
}

export interface DrawParams {
  width: number;
  stripH: number;
  leads: string[];
  view: View;
  fs: number;
  mvPerStrip: number;
  segments: Segment[];
  annotations: Annotation[];
  tiers: Record<string, Tier>;
  hiddenTiers: string[];
  selectedId: string | null;
  predictions: Prediction[];
  predictionEdits: Record<string, number>;
  selectedPredictionId: string | null;
  cursor: number | null;
  selection: [number, number] | null;
  preview: [number, number] | null;
  previewColor: string;
  annotationLead: string | null;
}

/** Median of visible values per lead (used to centre each strip). */
export function baselines(segments: Segment[], leads: string[], view: View): Record<string, number> {
  const out: Record<string, number> = {};
  for (const lead of leads) {
    const vals: number[] = [];
    for (const seg of segments) {
      const d = seg.chunk.leads[lead];
      if (!d) continue;
      const b = seg.chunk.bucket;
      const arr = d.values ?? d.min ?? [];
      const step = Math.max(1, Math.floor(arr.length / 800));
      for (let i = 0; i < arr.length; i += step) {
        const s = seg.chunk.start + i * b;
        if (s < Math.max(view.start, seg.from) || s >= Math.min(view.end, seg.to)) continue;
        vals.push(d.values ? d.values[i] : (d.min![i] + d.max![i]) / 2);
      }
    }
    if (!vals.length) out[lead] = 0;
    else {
      vals.sort((a, b) => a - b);
      out[lead] = vals[Math.floor(vals.length / 2)];
    }
  }
  return out;
}

function hexA(hex: string, a: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

export function drawWaveform(ctx: CanvasRenderingContext2D, p: DrawParams, dpr = 1): void {
  const { width, stripH, leads, view, fs } = p;
  const H = stripH * leads.length;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, width, H);
  const span = view.end - view.start;
  const pxPerSec = (width / span) * fs;
  const pxPerMv = stripH / p.mvPerStrip;
  const X = (s: number) => sampleToX(s, view, width);

  // --- ECG paper grid -------------------------------------------------------
  const { minor, major } = gridSpacing(pxPerSec, 5);
  const t0 = view.start / fs;
  const t1 = view.end / fs;
  const drawVLines = (step: number, color: string) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) {
      const x = Math.round(X(t * fs)) + 0.5;
      ctx.moveTo(x, 0);
      ctx.lineTo(x, H);
    }
    ctx.stroke();
  };
  drawVLines(minor, '#fbe3e3');
  drawVLines(major, '#f3b8b8');
  const mvMinor = 0.1 * pxPerMv >= 4 ? 0.1 : 0.5;
  const mvMajor = mvMinor === 0.1 ? 0.5 : 1;
  for (let li = 0; li < leads.length; li++) {
    const mid = li * stripH + stripH / 2;
    for (const [step, color] of [
      [mvMinor, '#fbe3e3'],
      [mvMajor, '#f3b8b8'],
    ] as const) {
      ctx.strokeStyle = color;
      ctx.beginPath();
      const half = p.mvPerStrip / 2;
      for (let mv = -Math.floor(half / step) * step; mv <= half; mv += step) {
        const y = Math.round(mid - mv * pxPerMv) + 0.5;
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
      }
      ctx.stroke();
    }
    ctx.strokeStyle = '#cbd5e1';
    ctx.beginPath();
    ctx.moveTo(0, (li + 1) * stripH - 0.5);
    ctx.lineTo(width, (li + 1) * stripH - 0.5);
    ctx.stroke();
  }

  // --- annotation overlays (under the trace) -------------------------------
  const visible = p.annotations.filter(
    (a) => !p.hiddenTiers.includes(a.tier) && a.start_sample < view.end && (a.end_sample ?? a.start_sample + 1) > view.start,
  );
  const stripsFor = (lead: string | null) =>
    lead === null ? leads.map((_, i) => i) : leads.indexOf(lead) >= 0 ? [leads.indexOf(lead)] : [];
  for (const a of visible) {
    const color = p.tiers[a.tier]?.color ?? '#334155';
    const sel = a.id === p.selectedId;
    for (const li of stripsFor(a.lead)) {
      const top = li * stripH;
      if (a.end_sample !== null) {
        const x0 = X(a.start_sample);
        const x1 = X(a.end_sample);
        const band = a.lead === null && p.tiers[a.tier]?.scope === 'global';
        ctx.fillStyle = hexA(color, band ? (sel ? 0.6 : 0.35) : sel ? 0.3 : 0.11);
        ctx.fillRect(x0, top, Math.max(1, x1 - x0), band ? 5 : stripH);
        ctx.strokeStyle = hexA(color, sel ? 1 : 0.55);
        ctx.lineWidth = sel ? 2 : 1;
        ctx.beginPath();
        ctx.moveTo(x0, top);
        ctx.lineTo(x0, top + stripH);
        ctx.moveTo(x1, top);
        ctx.lineTo(x1, top + stripH);
        ctx.stroke();
      } else {
        const x = X(a.start_sample);
        ctx.strokeStyle = hexA(color, sel ? 1 : 0.8);
        ctx.lineWidth = sel ? 2.5 : 1.25;
        ctx.beginPath();
        ctx.moveTo(x, top);
        ctx.lineTo(x, top + stripH);
        ctx.stroke();
      }
    }
  }
  if (p.selection) {
    const [a, b] = p.selection;
    ctx.fillStyle = 'rgba(37,99,235,0.10)';
    ctx.fillRect(X(a), 0, X(b) - X(a), H);
  }
  if (p.preview) {
    const [a, b] = p.preview;
    ctx.fillStyle = hexA(p.previewColor, 0.22);
    ctx.fillRect(X(a), 0, X(b) - X(a), H);
  }

  // --- signal trace ---------------------------------------------------------
  const base = baselines(p.segments, leads, view);
  const segs = [...p.segments].sort((a, b) => a.from - b.from);
  const pxPerSample = width / span;
  for (let li = 0; li < leads.length; li++) {
    const lead = leads[li];
    const mid = li * stripH + stripH / 2;
    const Y = (v: number) => mid - (v - base[lead]) * pxPerMv;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, li * stripH, width, stripH);
    ctx.clip();
    ctx.strokeStyle = lead === p.annotationLead ? '#0f172a' : '#1e293b';
    ctx.lineWidth = 1.1;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    let started = false;
    for (const seg of segs) {
      const d = seg.chunk.leads[lead];
      if (!d) continue;
      const b = seg.chunk.bucket;
      const s0 = seg.chunk.start;
      const lo = Math.max(seg.from, view.start - b * 2);
      const hi = Math.min(seg.to, view.end + b * 2);
      const i0 = Math.max(0, Math.floor((lo - s0) / b));
      const i1 = Math.min((d.values ?? d.min ?? []).length, Math.ceil((hi - s0) / b));
      for (let i = i0; i < i1; i++) {
        const x = X(s0 + i * b);
        if (d.values) {
          const y = Y(d.values[i]);
          if (!started) {
            ctx.moveTo(x, y);
            started = true;
          } else ctx.lineTo(x, y);
        } else {
          const ya = Y(d.max![i]);
          const yb = Y(d.min![i]);
          const [first, second] = i % 2 ? [yb, ya] : [ya, yb];
          if (!started) {
            ctx.moveTo(x, first);
            started = true;
          } else ctx.lineTo(x, first);
          ctx.lineTo(x, second);
        }
      }
    }
    ctx.stroke();
    if (pxPerSample >= 6) {
      ctx.fillStyle = '#0f172a';
      for (const seg of segs) {
        const d = seg.chunk.leads[lead];
        if (!d?.values) continue;
        const s0 = seg.chunk.start;
        for (let s = Math.max(view.start, seg.from); s < Math.min(view.end, seg.to); s++) {
          const v = d.values[s - s0];
          if (v === undefined) continue;
          ctx.beginPath();
          ctx.arc(X(s), Y(v), 1.6, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }
    ctx.restore();
  }

  // --- predictions ------------------------------------------------------------
  ctx.setLineDash([4, 3]);
  for (const pr of p.predictions) {
    if (pr.status !== 'pending') continue;
    const s = p.predictionEdits[pr.id] ?? pr.start_sample;
    if (s >= view.end || (pr.end_sample ?? s + 1) <= view.start) continue;
    const sel = pr.id === p.selectedPredictionId;
    ctx.strokeStyle = sel ? '#c2410c' : 'rgba(234,88,12,0.85)';
    ctx.lineWidth = sel ? 2 : 1.25;
    for (const li of stripsFor(pr.lead)) {
      const top = li * stripH;
      ctx.beginPath();
      if (pr.end_sample === null) {
        ctx.moveTo(X(s), top);
        ctx.lineTo(X(s), top + stripH);
      } else {
        ctx.rect(X(pr.start_sample), top + 2, X(pr.end_sample) - X(pr.start_sample), stripH - 4);
      }
      ctx.stroke();
    }
  }
  ctx.setLineDash([]);

  // --- cursor -------------------------------------------------------------------
  if (p.cursor !== null && p.cursor >= view.start && p.cursor <= view.end) {
    const x = Math.round(X(p.cursor)) + 0.5;
    ctx.strokeStyle = '#dc2626';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, H);
    ctx.stroke();
  }
}

/** Sample value (mV) at an exact index from loaded raw chunks, if available. */
export function valueAt(segments: Segment[], lead: string, sample: number): number | null {
  for (const seg of segments) {
    const d = seg.chunk.leads[lead];
    if (!d?.values || seg.chunk.bucket !== 1) continue;
    const i = sample - seg.chunk.start;
    if (i >= 0 && i < d.values.length) return d.values[i];
  }
  return null;
}

/** Exact value at raw resolution, otherwise the [min, max] of the bucket containing the sample. */
export function readoutAt(segments: Segment[], lead: string, sample: number): string | null {
  const v = valueAt(segments, lead, sample);
  if (v !== null) return `${v.toFixed(3)} mV`;
  for (const seg of segments) {
    const d = seg.chunk.leads[lead];
    if (!d?.min || !d.max) continue;
    const i = Math.floor((sample - seg.chunk.start) / seg.chunk.bucket);
    if (i >= 0 && i < d.min.length) return `[${d.min[i].toFixed(3)}, ${d.max[i].toFixed(3)}] mV`;
  }
  return null;
}
