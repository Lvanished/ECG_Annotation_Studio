import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { MeasurementResult } from '../api/types';
import { annEnd } from '../lib/annotations';
import { useEditor } from '../store/editor';

type Tab = 'measurements' | 'quality' | 'validation' | 'history';

export function AnalysisPanel() {
  const [tab, setTab] = useState<Tab>('measurements');
  const rec = useEditor((s) => s.recording);
  if (!rec) return null;
  return (
    <section className="flex h-full min-h-0 flex-col bg-white" data-testid="analysis-panel">
      <div className="flex border-b border-slate-200 bg-slate-50">
        {(['measurements', 'quality', 'validation', 'history'] as Tab[]).map((t) => (
          <button
            key={t}
            className={`px-3 py-1 text-2xs font-semibold uppercase tracking-wide ${tab === t ? 'border-b-2 border-blue-600 text-blue-700' : 'text-slate-500'}`}
            onClick={() => setTab(t)}
            data-testid={`tab-${t}`}
          >
            {t === 'quality' ? 'signal quality' : t}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {tab === 'measurements' && <Measurements />}
        {tab === 'quality' && <Quality />}
        {tab === 'validation' && <Validation />}
        {tab === 'history' && <History />}
      </div>
    </section>
  );
}

function fmt(v: number | null, unit: string) {
  if (v === null) return 'N/A';
  return unit === 'mV' ? v.toFixed(3) : v.toFixed(1);
}

function Measurements() {
  const rec = useEditor((s) => s.recording)!;
  const view = useEditor((s) => s.view);
  const lead = useEditor((s) => s.annotationLead);
  const cursor = useEditor((s) => s.cursor);
  const working = useEditor((s) => s.working);
  const docVersion = useEditor((s) => s.docVersion);
  const margin = Math.round(rec.fs * 3);
  const subset = useMemo(
    () =>
      Object.values(working)
        .filter((a) => a.start_sample < view.end + margin && annEnd(a) > view.start - margin)
        .map((a) => ({ id: a.id, tier: a.tier, label: a.label, lead: a.lead, start_sample: a.start_sample, end_sample: a.end_sample })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [docVersion, view.start, view.end],
  );
  const q = useQuery({
    queryKey: ['measure', rec.id, lead, view.start, view.end, docVersion],
    queryFn: () =>
      api<MeasurementResult>(`/recordings/${rec.id}/measurements`, {
        method: 'POST',
        json: { lead, start_sample: view.start, end_sample: view.end, annotations: subset },
      }),
    placeholderData: (prev) => prev,
  });
  const m = q.data;
  if (!m) return <p className="p-2 text-slate-500">Computing…</p>;
  const ref = cursor ?? (view.start + view.end) / 2;
  const beat = m.beats.length ? m.beats.reduce((a, b) => (Math.abs(b.r_sample - ref) < Math.abs(a.r_sample - ref) ? b : a)) : null;
  return (
    <div className="grid grid-cols-[minmax(0,3fr)_minmax(0,2fr)] gap-2 p-2" data-testid="measurements">
      <div>
        <div className="lbl mb-1">
          Beat nearest {cursor !== null ? 'cursor' : 'view centre'}
          {beat ? ` · anchor ${beat.anchor} @ ${beat.r_sample}` : ''} · lead {lead ?? 'all'} · includes unsaved edits
        </div>
        {beat ? (
          <table className="w-full font-mono text-2xs">
            <thead>
              <tr className="text-left text-slate-500">
                <th>measurement</th>
                <th>value</th>
                <th>source samples</th>
                <th>method</th>
              </tr>
            </thead>
            <tbody>
              {beat.values.map((v) => (
                <tr key={v.name} className="border-t border-slate-100" data-testid={`measure-${v.name}`}>
                  <td className="pr-2">
                    {v.name}
                    {v.experimental && <span className="ml-1 rounded bg-amber-100 px-0.5 text-amber-800">exp</span>}
                  </td>
                  <td className={`pr-2 font-semibold ${v.value === null ? 'text-slate-400' : ''}`} title={v.reason ?? ''}>
                    {fmt(v.value, v.unit)} {v.value !== null && v.unit}
                  </td>
                  <td className="pr-2 text-slate-600">{v.value !== null ? v.samples.join(' → ') : v.reason}</td>
                  <td className="truncate text-slate-500" title={v.method}>{v.method}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-slate-500">N/A — no beat anchors (R_peak points, Beat points or QRS intervals) in view for this lead.</p>
        )}
      </div>
      <div>
        <div className="lbl mb-1">Window summary ({m.beats.length} beats)</div>
        <table className="w-full font-mono text-2xs">
          <thead>
            <tr className="text-left text-slate-500">
              <th>measurement</th>
              <th>n</th>
              <th>median</th>
              <th>mean ± sd</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(m.summary).map(([k, s]) => (
              <tr key={k} className="border-t border-slate-100">
                <td>{k}</td>
                <td>{s.n}</td>
                <td>{fmt(s.median, s.unit)}</td>
                <td>
                  {fmt(s.mean, s.unit)} ± {fmt(s.std, s.unit)} {s.unit}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Quality() {
  const rec = useEditor((s) => s.recording)!;
  const view = useEditor((s) => s.view);
  const leads = useEditor((s) => s.displayLeads);
  const q = useQuery({
    queryKey: ['quality', rec.id, leads.join(','), view.start, view.end],
    queryFn: () => api<{ leads: Record<string, Record<string, unknown>> }>(`/recordings/${rec.id}/quality?start=${view.start}&end=${view.end}&leads=${encodeURIComponent(leads.join(','))}`),
    placeholderData: (p) => p,
  });
  if (!q.data) return <p className="p-2 text-slate-500">Computing…</p>;
  const keys = ['amplitude_range_mv', 'flatline_fraction', 'clipping_fraction', 'baseline_wander_ratio', 'high_frequency_noise_ratio', 'powerline_ratio'];
  return (
    <div className="p-2">
      <p className="mb-1 text-2xs text-amber-700">Descriptive indicators for the visible window; flag thresholds are heuristic and not validated.</p>
      <table className="w-full font-mono text-2xs">
        <thead>
          <tr className="text-left text-slate-500">
            <th>lead</th>
            {keys.map((k) => (
              <th key={k}>{k.replace(/_/g, ' ')}</th>
            ))}
            <th>flags</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(q.data.leads).map(([l, v]) => (
            <tr key={l} className="border-t border-slate-100">
              <td className="font-bold">{l}</td>
              {keys.map((k) => (
                <td key={k}>{typeof v[k] === 'number' ? (v[k] as number).toFixed(3) : 'N/A'}</td>
              ))}
              <td>{Array.isArray(v.flags) ? (v.flags as string[]).join(', ') || '—' : String(v.status ?? '')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Validation() {
  const rec = useEditor((s) => s.recording)!;
  const server = useEditor((s) => s.server);
  const st = useEditor.getState;
  const q = useQuery({
    queryKey: ['validate', rec.id, Object.keys(server).length],
    queryFn: () => api<{ issues: { severity: string; annotation_id: string; message: string }[]; n_issues: number }>(`/recordings/${rec.id}/validate`),
  });
  if (!q.data) return <p className="p-2 text-slate-500">Validating saved annotations…</p>;
  return (
    <div className="p-2 text-2xs">
      <div className="lbl mb-1">{q.data.n_issues} issue(s) in saved annotations (ontology + parent/child containment)</div>
      <ul>
        {q.data.issues.slice(0, 200).map((i, k) => (
          <li key={k} className="cursor-pointer border-t border-slate-100 py-0.5 hover:bg-slate-50" onClick={() => {
            const a = st().working[i.annotation_id];
            if (a) {
              st().select(a.id);
              st().center(a.start_sample);
            }
          }}>
            <span className={i.severity === 'error' ? 'text-red-700' : 'text-amber-700'}>{i.severity}</span> {i.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

function History() {
  const rec = useEditor((s) => s.recording)!;
  const server = useEditor((s) => s.server);
  const q = useQuery({
    queryKey: ['rec-history', rec.id, server],
    queryFn: () => api<{ annotation_id: string; revision: number; operation: string; timestamp: string; actor: string; label: string; start_sample: number; end_sample: number | null }[]>(`/recordings/${rec.id}/history?limit=200`),
  });
  return (
    <table className="m-2 w-[calc(100%-1rem)] font-mono text-2xs">
      <tbody>
        {(q.data ?? []).map((h, i) => (
          <tr key={i} className="border-t border-slate-100">
            <td className="pr-2 text-slate-500">{new Date(h.timestamp).toLocaleString()}</td>
            <td className="pr-2">{h.operation}</td>
            <td className="pr-2">r{h.revision}</td>
            <td className="pr-2">{h.label}</td>
            <td className="pr-2">
              [{h.start_sample}
              {h.end_sample !== null ? `, ${h.end_sample})` : ']'}
            </td>
            <td className="text-slate-500">{h.actor}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
