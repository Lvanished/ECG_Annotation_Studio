import { useMemo, useRef } from 'react';
import type { Annotation, Ontology, Prediction, Tier } from '../api/types';
import { annEnd, overlapConflict, tierAccepts, visibleOnLead } from '../lib/annotations';
import { formatTime, gridSpacing, sampleToX, xToSample } from '../lib/viewport';
import { useSize } from '../hooks/useSize';
import { useEditor } from '../store/editor';
import { addAnnotation } from '../store/actions';
import { GUTTER } from './layout';

type DragMode = 'start' | 'end' | 'move' | 'point';

interface Props {
  onto: Ontology;
  predictions: Prediction[];
}

export function TierPanel({ onto, predictions }: Props) {
  const rec = useEditor((s) => s.recording)!;
  const view = useEditor((s) => s.view);
  const working = useEditor((s) => s.working);
  const selectedId = useEditor((s) => s.selectedId);
  const hiddenTiers = useEditor((s) => s.hiddenTiers);
  const collapsed = useEditor((s) => s.collapsedTiers);
  const activeTier = useEditor((s) => s.activeTier);
  const annotationLead = useEditor((s) => s.annotationLead);
  const cursor = useEditor((s) => s.cursor);
  const predictionEdits = useEditor((s) => s.predictionEdits);
  const selectedPredictionId = useEditor((s) => s.selectedPredictionId);
  const st = useEditor.getState;
  const rulerRef = useRef<HTMLDivElement>(null);
  const { width } = useSize(rulerRef);

  const tiers = useMemo(() => [...onto.tiers].sort((a, b) => a.order - b.order), [onto.tiers]);
  const byTier = useMemo(() => {
    const m: Record<string, Annotation[]> = {};
    for (const a of Object.values(working)) {
      if (a.start_sample >= view.end || annEnd(a) <= view.start) continue;
      if (!visibleOnLead(a, annotationLead)) continue;
      (m[a.tier] ??= []).push(a);
    }
    return m;
  }, [working, view.start, view.end, annotationLead]);
  const pending = predictions.filter(
    (p) => p.status === 'pending' && (p.end_sample ?? p.start_sample + 1) > view.start && p.start_sample < view.end,
  );
  const X = (s: number) => sampleToX(s, view, width);

  const trackSample = (clientX: number, el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    return xToSample(clientX - r.left, st().view, r.width);
  };

  const startDrag = (e: React.PointerEvent, ann: Annotation, mode: DragMode) => {
    e.stopPropagation();
    e.preventDefault();
    st().select(ann.id);
    st().setActiveTier(ann.tier);
    const track = (e.currentTarget as HTMLElement).closest('[data-track]') as HTMLElement;
    const s0 = trackSample(e.clientX, track);
    const orig = { start: ann.start_sample, end: ann.end_sample };
    const n = rec.n_samples;
    let begun = false;
    let changed = false;
    const move = (ev: PointerEvent) => {
      if (!begun) {
        if (Math.abs(ev.clientX - e.clientX) < 2) return;
        st().beginGesture();
        begun = true;
      }
      const ds = trackSample(ev.clientX, track) - s0;
      let start = orig.start;
      let end = orig.end;
      if (mode === 'point') start = Math.max(0, Math.min(n - 1, orig.start + ds));
      else if (mode === 'start') start = Math.max(0, Math.min((orig.end ?? n) - 1, orig.start + ds));
      else if (mode === 'end') end = Math.max(orig.start + 1, Math.min(n, (orig.end ?? 0) + ds));
      else if (mode === 'move' && orig.end !== null) {
        const len = orig.end - orig.start;
        start = Math.max(0, Math.min(n - len, orig.start + ds));
        end = start + len;
      }
      changed = start !== orig.start || end !== orig.end;
      st().live((w) => ({ ...w, [ann.id]: { ...w[ann.id], start_sample: start, end_sample: end } }));
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      if (!begun) return;
      const cur = st().working[ann.id];
      const tier = onto.tiers.find((t) => t.name === ann.tier);
      const clash = cur && overlapConflict(Object.values(st().working), tier, cur);
      if (clash) {
        st().live((w) => ({ ...w, [ann.id]: { ...w[ann.id], start_sample: orig.start, end_sample: orig.end } }));
        st().endGesture(false);
        st().setStatus(`Move rejected: would overlap ${clash.label} [${clash.start_sample}, ${clash.end_sample})`, 'error');
        return;
      }
      st().endGesture(changed);
      if (changed && cur)
        st().setStatus(
          `${cur.label}: ${cur.end_sample === null ? `sample ${cur.start_sample}` : `[${cur.start_sample}, ${cur.end_sample})`} (unsaved)`,
        );
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const startPredDrag = (e: React.PointerEvent, p: Prediction) => {
    e.stopPropagation();
    e.preventDefault();
    st().selectPrediction(p.id);
    if (p.kind !== 'point') return;
    const track = (e.currentTarget as HTMLElement).closest('[data-track]') as HTMLElement;
    const s0 = trackSample(e.clientX, track);
    const base = st().predictionEdits[p.id] ?? p.start_sample;
    const move = (ev: PointerEvent) => {
      const s = Math.max(0, Math.min(rec.n_samples - 1, base + trackSample(ev.clientX, track) - s0));
      st().editPrediction(p.id, s === p.start_sample ? null : s);
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const ticks = useMemo(() => {
    if (!width) return [];
    const { major } = gridSpacing((width / (view.end - view.start)) * rec.fs, 70);
    const out: number[] = [];
    for (let t = Math.ceil(view.start / rec.fs / major) * major; t * rec.fs <= view.end; t += major) out.push(t);
    return out;
  }, [width, view.start, view.end, rec.fs]);

  const visibleTiers = tiers.filter((t) => !hiddenTiers.includes(t.name));

  return (
    <div className="flex min-h-0 flex-1 flex-col border-t border-slate-300 bg-white" data-testid="tier-panel">
      {/* time axis */}
      <div className="stable-gutter flex overflow-hidden border-b border-slate-200 bg-slate-50" style={{ height: 20 }}>
        <div className="shrink-0 px-2 text-2xs leading-5 text-slate-500" style={{ width: GUTTER }}>
          time / sample
        </div>
        <div ref={rulerRef} className="relative flex-1">
          {ticks.map((t) => (
            <div key={t} className="absolute top-0 h-full border-l border-slate-300 pl-0.5 font-mono text-2xs text-slate-500" style={{ left: X(t * rec.fs) }}>
              {formatTime(t)}
            </div>
          ))}
          {cursor !== null && cursor >= view.start && cursor <= view.end && (
            <div className="absolute top-0 h-full border-l border-red-500 pl-0.5 font-mono text-2xs text-red-600" style={{ left: X(cursor) }}>
              {cursor}
            </div>
          )}
        </div>
      </div>
      <div className="stable-gutter min-h-0 flex-1 overflow-y-auto">
        {visibleTiers.map((t, idx) => (
          <TierRow
            key={t.id}
            tier={t}
            index={idx}
            anns={byTier[t.name] ?? []}
            active={t.name === activeTier}
            collapsed={collapsed.includes(t.name)}
            selectedId={selectedId}
            X={X}
            onDrag={startDrag}
            onTrackClick={(sample) => {
              st().setActiveTier(t.name);
              st().setCursor(sample);
              st().select(null);
            }}
            onTrackDouble={(sample) => {
              if (tierAccepts(t, 'point')) addAnnotation(onto, t.name, sample, null);
              else st().setStatus(`Tier "${t.name}" holds intervals: drag on the waveform in Annotate mode, or select a range and press Enter`);
            }}
            trackSample={trackSample}
            cursor={cursor}
          />
        ))}
        {/* prediction layer */}
        <div className="flex border-b border-orange-200" style={{ height: 30 }} data-testid="prediction-row">
          <div className="flex shrink-0 items-center gap-1 border-r border-slate-200 bg-orange-50 px-2 text-2xs font-semibold text-orange-800" style={{ width: GUTTER }}>
            Predictions ({predictions.filter((p) => p.status === 'pending').length} pending)
          </div>
          <div data-track className="relative flex-1 overflow-hidden bg-[repeating-linear-gradient(45deg,#fff7ed,#fff7ed_6px,#ffffff_6px,#ffffff_12px)]">
            {pending.slice(0, 600).map((p) => {
              const s = predictionEdits[p.id] ?? p.start_sample;
              const sel = p.id === selectedPredictionId;
              if (p.end_sample === null)
                return (
                  <div
                    key={p.id}
                    data-testid={`pred-${p.id}`}
                    data-start={s}
                    title={`${p.label} @ ${s}${s !== p.start_sample ? ` (moved from ${p.start_sample})` : ''}`}
                    onPointerDown={(e) => startPredDrag(e, p)}
                    className="absolute top-0 h-full w-[9px] -translate-x-1/2 cursor-ew-resize"
                    style={{ left: X(s) }}
                  >
                    <div className={`mx-auto h-full border-l-2 border-dashed ${sel ? 'border-orange-700' : 'border-orange-500'}`} />
                  </div>
                );
              return (
                <div
                  key={p.id}
                  data-testid={`pred-${p.id}`}
                  onPointerDown={(e) => startPredDrag(e, p)}
                  className={`absolute top-1 bottom-1 cursor-pointer truncate border border-dashed px-0.5 text-2xs ${sel ? 'border-orange-700 bg-orange-200/70' : 'border-orange-500 bg-orange-100/60'}`}
                  style={{ left: X(p.start_sample), width: Math.max(2, X(p.end_sample) - X(p.start_sample)) }}
                  title={`${p.label} [${p.start_sample}, ${p.end_sample})`}
                >
                  {p.label}
                </div>
              );
            })}
          </div>
        </div>
        {hiddenTiers.length > 0 && (
          <div className="flex flex-wrap items-center gap-1 border-b border-slate-200 bg-slate-50 px-2 py-1 text-2xs">
            <span className="text-slate-500">Hidden tiers:</span>
            {hiddenTiers.map((h) => (
              <button key={h} className="btn py-0" onClick={() => st().toggleHidden(h)} data-testid={`show-tier-${h}`}>
                {h} ↺
              </button>
            ))}
          </div>
        )}
      </div>
      <Overview />
    </div>
  );
}

interface RowProps {
  tier: Tier;
  index: number;
  anns: Annotation[];
  active: boolean;
  collapsed: boolean;
  selectedId: string | null;
  X: (s: number) => number;
  onDrag: (e: React.PointerEvent, a: Annotation, m: DragMode) => void;
  onTrackClick: (sample: number) => void;
  onTrackDouble: (sample: number) => void;
  trackSample: (clientX: number, el: HTMLElement) => number;
  cursor: number | null;
}

function TierRow({ tier, index, anns, active, collapsed, selectedId, X, onDrag, onTrackClick, onTrackDouble, trackSample, cursor }: RowProps) {
  const st = useEditor.getState;
  const h = collapsed ? 12 : 30;
  return (
    <div className="flex border-b border-slate-200" style={{ height: h }} data-testid={`tier-row-${tier.name}`}>
      <div
        className={`flex shrink-0 items-center gap-1 border-r border-slate-200 px-1 ${active ? 'bg-blue-50' : 'bg-slate-50'}`}
        style={{ width: GUTTER }}
      >
        <button className="w-3 text-2xs text-slate-500" title="Collapse/expand" onClick={() => st().toggleCollapsed(tier.name)}>
          {collapsed ? '▸' : '▾'}
        </button>
        <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: tier.color }} />
        {!collapsed && (
          <button
            className={`min-w-0 flex-1 truncate text-left text-2xs ${active ? 'font-bold text-blue-800' : 'text-slate-700'}`}
            title={`${tier.name} · ${tier.kind} · ${tier.scope} · overlap: ${tier.overlap_policy}${index < 9 ? ` · key ${index + 1}` : ''}`}
            onClick={() => st().setActiveTier(tier.name)}
            data-testid={`tier-name-${tier.name}`}
          >
            {index < 9 && <span className="mr-1 text-slate-400">{index + 1}</span>}
            {tier.name}
            <span className="ml-1 text-slate-400">{tier.kind === 'point' ? '•' : tier.kind === 'interval' ? '▭' : '•▭'}</span>
          </button>
        )}
        <button className="text-2xs text-slate-400 hover:text-slate-700" title="Hide tier" onClick={() => st().toggleHidden(tier.name)} data-testid={`hide-tier-${tier.name}`}>
          ✕
        </button>
      </div>
      <div
        data-track
        className={`relative flex-1 overflow-hidden ${active ? 'bg-blue-50/30' : ''}`}
        onPointerDown={(e) => {
          if (e.target === e.currentTarget) onTrackClick(trackSample(e.clientX, e.currentTarget));
        }}
        onDoubleClick={(e) => {
          if (e.target === e.currentTarget) onTrackDouble(trackSample(e.clientX, e.currentTarget));
        }}
      >
        {cursor !== null && <div className="pointer-events-none absolute top-0 h-full border-l border-red-400/70" style={{ left: X(cursor) }} />}
        {anns.map((a) => {
          const sel = a.id === selectedId;
          const common = {
            'data-testid': `ann-${a.id}`,
            'data-label': a.label,
            'data-start': a.start_sample,
            'data-end': a.end_sample ?? '',
            'data-lead': a.lead ?? '',
          };
          if (a.end_sample === null) {
            return (
              <div
                key={a.id}
                {...common}
                className="absolute top-0 h-full w-[11px] -translate-x-1/2 cursor-ew-resize"
                style={{ left: X(a.start_sample) }}
                onPointerDown={(e) => onDrag(e, a, 'point')}
                title={`${a.label} @ ${a.start_sample}${a.lead ? ` (${a.lead})` : ' (global)'} · ${a.source}/${a.review_status}`}
              >
                <div className="mx-auto h-full" style={{ borderLeft: `${sel ? 3 : 2}px solid ${tier.color}` }} />
                {!collapsed && (
                  <span
                    className={`pointer-events-none absolute left-[7px] top-0 whitespace-nowrap rounded px-0.5 text-2xs ${sel ? 'bg-amber-200 font-bold' : 'bg-white/80'}`}
                    style={{ color: tier.color }}
                  >
                    {a.label}
                  </span>
                )}
              </div>
            );
          }
          const x0 = X(a.start_sample);
          const x1 = X(a.end_sample);
          return (
            <div
              key={a.id}
              {...common}
              className={`absolute top-0.5 bottom-0.5 cursor-grab overflow-hidden rounded-sm text-center text-2xs leading-6 ${sel ? 'ring-2 ring-amber-500' : ''}`}
              style={{
                left: x0,
                width: Math.max(2, x1 - x0),
                background: `${tier.color}${sel ? '55' : '26'}`,
                borderLeft: `1px solid ${tier.color}`,
                borderRight: `1px solid ${tier.color}`,
                color: '#0f172a',
              }}
              onPointerDown={(e) => onDrag(e, a, 'move')}
              title={`${a.label} [${a.start_sample}, ${a.end_sample})${a.lead ? ` (${a.lead})` : ' (global)'} · ${a.source}/${a.review_status}`}
            >
              {!collapsed && <span className="pointer-events-none truncate px-1">{a.label}</span>}
              <div data-handle="start" className="absolute left-0 top-0 h-full w-[6px] cursor-col-resize hover:bg-black/20" onPointerDown={(e) => onDrag(e, a, 'start')} />
              <div data-handle="end" className="absolute right-0 top-0 h-full w-[6px] cursor-col-resize hover:bg-black/20" onPointerDown={(e) => onDrag(e, a, 'end')} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Overview() {
  const rec = useEditor((s) => s.recording)!;
  const view = useEditor((s) => s.view);
  const ref = useRef<HTMLDivElement>(null);
  const { width } = useSize(ref);
  const st = useEditor.getState;
  const n = rec.n_samples;
  const go = (clientX: number) => {
    const r = ref.current!.getBoundingClientRect();
    st().center(Math.round(((clientX - r.left) / r.width) * n));
  };
  return (
    <div className="stable-gutter flex border-t border-slate-300 bg-slate-100" style={{ height: 16 }}>
      <div className="shrink-0 px-2 text-2xs leading-4 text-slate-500" style={{ width: GUTTER }}>
        {formatTime(n / rec.fs)} total
      </div>
      <div
        ref={ref}
        className="relative flex-1 cursor-pointer"
        data-testid="overview"
        onPointerDown={(e) => {
          (e.target as HTMLElement).setPointerCapture(e.pointerId);
          go(e.clientX);
        }}
        onPointerMove={(e) => e.buttons === 1 && go(e.clientX)}
      >
        <div
          className="absolute top-0.5 bottom-0.5 rounded-sm border border-blue-600 bg-blue-500/30"
          style={{ left: (view.start / n) * width, width: Math.max(3, ((view.end - view.start) / n) * width) }}
        />
      </div>
    </div>
  );
}
