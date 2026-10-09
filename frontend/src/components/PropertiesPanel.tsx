import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, errMsg } from '../api/client';
import type { Annotation, AttrSpec, Dataset, Ontology, Prediction, PredictionRun } from '../api/types';
import { isTemp, labelsForTier } from '../lib/annotations';
import { formatTime } from '../lib/viewport';
import { useEditor } from '../store/editor';
import { acceptPrediction, deleteSelected, updateAnnotation } from '../store/actions';

interface Props {
  onto: Ontology;
  runs: PredictionRun[];
  datasets: Dataset[];
}

export function PropertiesPanel({ onto, runs, datasets }: Props) {
  const selectedId = useEditor((s) => s.selectedId);
  const selectedPredictionId = useEditor((s) => s.selectedPredictionId);
  const ann = useEditor((s) => (s.selectedId ? s.working[s.selectedId] : undefined));
  const rec = useEditor((s) => s.recording);
  const pred = runs.flatMap((r) => r.predictions).find((p) => p.id === selectedPredictionId);
  return (
    <aside className="flex h-full min-h-0 flex-col overflow-y-auto bg-white" data-testid="properties-panel">
      <div className="panel-title">{ann ? 'Annotation properties' : pred ? 'Prediction review' : 'Recording'}</div>
      {ann && selectedId ? (
        <AnnotationEditor key={selectedId} ann={ann} onto={onto} />
      ) : pred ? (
        <PredictionReview pred={pred} run={runs.find((r) => r.id === pred.run_id)!} />
      ) : rec ? (
        <RecordingInfo datasets={datasets} />
      ) : (
        <p className="p-3 text-slate-500">No recording selected.</p>
      )}
      <RunsList runs={runs} />
      <Shortcuts />
    </aside>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="lbl">{label}</span>
      {children}
    </label>
  );
}

function NumInput({ value, onCommit, testid, min, max }: { value: number | null; onCommit: (v: number) => void; testid: string; min: number; max: number }) {
  const [txt, setTxt] = useState(value === null ? '' : String(value));
  useEffect(() => setTxt(value === null ? '' : String(value)), [value]);
  const commit = () => {
    const v = parseInt(txt, 10);
    if (Number.isFinite(v) && v >= min && v <= max && v !== value) onCommit(v);
    else setTxt(value === null ? '' : String(value));
  };
  return (
    <input
      className="inp font-mono"
      data-testid={testid}
      value={txt}
      onChange={(e) => setTxt(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === 'Enter' && (e.currentTarget as HTMLInputElement).blur()}
    />
  );
}

function AnnotationEditor({ ann, onto }: { ann: Annotation; onto: Ontology }) {
  const rec = useEditor((s) => s.recording)!;
  const server = useEditor((s) => s.server[ann.id]);
  const tier = onto.tiers.find((t) => t.name === ann.tier);
  const labels = labelsForTier(onto.labels, tier, ann.kind);
  const lab = onto.labels.find((l) => l.code === ann.label);
  const schema: Record<string, AttrSpec> = { note: { type: 'string' }, uncertain: { type: 'boolean' }, ...(lab?.attributes_schema ?? {}) };
  const fs = rec.fs;
  const [newKey, setNewKey] = useState('');
  const [newVal, setNewVal] = useState('');
  const dirty = !server || server !== ann;
  const tiersForKind = onto.tiers.filter((t) => t.kind === 'mixed' || t.kind === ann.kind);
  const hist = useQuery({
    queryKey: ['history', ann.id, server?.revision],
    queryFn: () => api<{ revision: number; operation: string; timestamp: string; actor: string; snapshot: Annotation }[]>(`/annotations/${ann.id}/history`),
    enabled: !isTemp(ann.id),
  });
  const setAttr = (k: string, v: unknown) => {
    const next = { ...ann.attributes };
    if (v === '' || v === undefined || v === null) delete next[k];
    else next[k] = v;
    updateAnnotation(ann.id, { attributes: next });
  };
  return (
    <div className="flex flex-col gap-2 p-2" data-testid="annotation-editor">
      <div className="flex items-center justify-between font-mono text-2xs text-slate-500">
        <span title={ann.id}>{isTemp(ann.id) ? 'new (unsaved)' : `id ${ann.id.slice(0, 8)}…`}</span>
        <span>
          rev {ann.revision || '–'} {dirty && <b className="text-amber-600">● modified</b>}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Tier">
          <select className="inp" value={ann.tier} data-testid="prop-tier" onChange={(e) => updateAnnotation(ann.id, { tier: e.target.value })}>
            {tiersForKind.map((t) => (
              <option key={t.id} value={t.name}>{t.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Lead">
          <select className="inp" value={ann.lead ?? ''} data-testid="prop-lead" onChange={(e) => updateAnnotation(ann.id, { lead: e.target.value || null })}>
            {rec.leads.map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
            <option value="">global (all leads)</option>
          </select>
        </Field>
      </div>
      <Field label="Label">
        {tier?.allow_free_labels ? (
          <input
            className="inp"
            data-testid="prop-label"
            defaultValue={ann.label}
            key={ann.label}
            onBlur={(e) => e.target.value.trim() && e.target.value.trim() !== ann.label && updateAnnotation(ann.id, { label: e.target.value.trim() })}
            onKeyDown={(e) => e.key === 'Enter' && (e.currentTarget as HTMLInputElement).blur()}
          />
        ) : (
          <select className="inp" value={ann.label} data-testid="prop-label" onChange={(e) => updateAnnotation(ann.id, { label: e.target.value })}>
            {!labels.some((l) => l.code === ann.label) && <option value={ann.label}>{ann.label} (not valid for tier)</option>}
            {labels.map((l) => (
              <option key={l.code} value={l.code}>
                {l.code} — {l.name}
              </option>
            ))}
          </select>
        )}
      </Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label={ann.kind === 'point' ? 'Sample' : 'Start sample'}>
          <NumInput
            testid="prop-start"
            value={ann.start_sample}
            min={0}
            max={(ann.end_sample ?? rec.n_samples) - 1}
            onCommit={(v) => updateAnnotation(ann.id, { start_sample: v })}
          />
        </Field>
        {ann.kind === 'interval' && (
          <Field label="End sample (excl.)">
            <NumInput testid="prop-end" value={ann.end_sample} min={ann.start_sample + 1} max={rec.n_samples} onCommit={(v) => updateAnnotation(ann.id, { end_sample: v })} />
          </Field>
        )}
      </div>
      <div className="font-mono text-2xs text-slate-600">
        t = {formatTime(ann.start_sample / fs)}
        {ann.end_sample !== null && ` → ${formatTime(ann.end_sample / fs)} · duration ${(((ann.end_sample - ann.start_sample) / fs) * 1000).toFixed(1)} ms (${ann.end_sample - ann.start_sample} samples)`}
      </div>
      <div className="lbl mt-1">Attributes</div>
      {Object.entries(schema).map(([k, spec]) => (
        <div key={k} className="grid grid-cols-[90px_1fr] items-center gap-1">
          <span className="truncate font-mono text-2xs" title={k}>{k}</span>
          {spec.type === 'enum' ? (
            <select className="inp" data-testid={`attr-${k}`} value={String(ann.attributes[k] ?? '')} onChange={(e) => setAttr(k, e.target.value)}>
              <option value="">—</option>
              {spec.values?.map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          ) : spec.type === 'boolean' ? (
            <input type="checkbox" data-testid={`attr-${k}`} checked={ann.attributes[k] === true} onChange={(e) => setAttr(k, e.target.checked ? true : undefined)} />
          ) : (
            <input
              className="inp"
              data-testid={`attr-${k}`}
              defaultValue={String(ann.attributes[k] ?? '')}
              key={`${k}-${String(ann.attributes[k] ?? '')}`}
              onBlur={(e) => e.target.value !== String(ann.attributes[k] ?? '') && setAttr(k, spec.type === 'number' ? Number(e.target.value) : e.target.value)}
            />
          )}
        </div>
      ))}
      {Object.entries(ann.attributes)
        .filter(([k]) => !(k in schema))
        .map(([k, v]) => (
          <div key={k} className="grid grid-cols-[90px_1fr_auto] items-center gap-1">
            <span className="truncate font-mono text-2xs">{k}</span>
            <span className="truncate font-mono text-2xs">{JSON.stringify(v)}</span>
            <button className="text-2xs text-red-600" onClick={() => setAttr(k, undefined)}>✕</button>
          </div>
        ))}
      <form
        className="grid grid-cols-[90px_1fr_auto] gap-1"
        onSubmit={(e) => {
          e.preventDefault();
          const key = newKey.startsWith('x_') ? newKey : `x_${newKey}`;
          if (newKey.trim()) setAttr(key, newVal);
          setNewKey('');
          setNewVal('');
        }}
      >
        <input className="inp" placeholder="x_key" value={newKey} onChange={(e) => setNewKey(e.target.value)} />
        <input className="inp" placeholder="value" value={newVal} onChange={(e) => setNewVal(e.target.value)} />
        <button className="btn" type="submit">+</button>
      </form>
      <Field label="Review status">
        <select
          className="inp"
          data-testid="prop-review"
          value={ann.review_status}
          onChange={(e) => updateAnnotation(ann.id, { review_status: e.target.value as Annotation['review_status'] })}
        >
          {['draft', 'needs_review', 'reviewed', 'rejected'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </Field>
      <div className="rounded bg-slate-50 p-1.5 font-mono text-2xs text-slate-600">
        <div>source: <b>{ann.source}</b> · ontology {ann.ontology_version}</div>
        {ann.beat_id && <div>beat_id: {ann.beat_id.slice(0, 8)}…</div>}
        {Object.keys(ann.provenance).length > 0 && (
          <details>
            <summary className="cursor-pointer">provenance</summary>
            <pre className="whitespace-pre-wrap break-all">{JSON.stringify(ann.provenance, null, 1)}</pre>
          </details>
        )}
      </div>
      <button className="btn btn-danger" onClick={() => deleteSelected()} data-testid="prop-delete">
        Delete annotation (Del)
      </button>
      {hist.data && (
        <div>
          <div className="lbl">Revision history</div>
          <ul className="max-h-40 overflow-y-auto font-mono text-2xs" data-testid="history-list">
            {hist.data.map((h) => (
              <li key={`${h.revision}-${h.operation}`} className="border-b border-slate-100 py-0.5">
                r{h.revision} {h.operation} · {h.snapshot.label} [{h.snapshot.start_sample}
                {h.snapshot.end_sample !== null ? `, ${h.snapshot.end_sample})` : ']'} · {h.actor} · {new Date(h.timestamp).toLocaleString()}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function PredictionReview({ pred, run }: { pred: Prediction; run: PredictionRun }) {
  const edit = useEditor((s) => s.predictionEdits[pred.id]);
  const qc = useQueryClient();
  const st = useEditor.getState;
  const start = edit ?? pred.start_sample;
  const refresh = () => qc.invalidateQueries({ queryKey: ['runs', pred.recording_id] });
  return (
    <div className="flex flex-col gap-2 p-2" data-testid="prediction-review">
      <div className="font-mono text-2xs">
        {pred.label} on {pred.lead ?? 'all leads'} · {pred.kind}
        <br />
        sample <b data-testid="pred-sample">{start}</b>
        {edit !== undefined && <span className="text-amber-700"> (moved from {pred.start_sample})</span>}
        {pred.end_sample !== null && ` → ${pred.end_sample}`}
        <br />
        status: {pred.status}
      </div>
      <div className="rounded bg-orange-50 p-1.5 text-2xs">
        {run.algorithm}@{run.algorithm_version}
        {run.experimental && <b className="ml-1 text-amber-700">EXPERIMENTAL</b>}
        <details>
          <summary className="cursor-pointer">parameters</summary>
          <pre className="whitespace-pre-wrap break-all font-mono">{JSON.stringify(run.parameters, null, 1)}</pre>
        </details>
      </div>
      {pred.status === 'pending' && (
        <>
          {pred.kind === 'point' && (
            <div className="flex items-center gap-1">
              <span className="lbl">Modify sample</span>
              <NumInput testid="pred-edit" value={start} min={0} max={1e9} onCommit={(v) => st().editPrediction(pred.id, v === pred.start_sample ? null : v)} />
            </div>
          )}
          <div className="flex gap-1">
            <button
              className="btn btn-primary"
              data-testid="pred-accept"
              onClick={async () => {
                const a = await acceptPrediction(pred, start);
                await refresh();
                if (a) st().select(a.id);
              }}
            >
              {edit !== undefined ? 'Accept modified' : 'Accept'}
            </button>
            <button
              className="btn btn-danger"
              data-testid="pred-reject"
              onClick={async () => {
                try {
                  await api(`/predictions/${pred.id}/reject`, { method: 'POST' });
                  st().setStatus('Prediction rejected', 'ok');
                  st().selectPrediction(null);
                  await refresh();
                } catch (e) {
                  st().setStatus(errMsg(e), 'error');
                }
              }}
            >
              Reject
            </button>
          </div>
          <p className="text-2xs text-slate-500">Drag the dashed marker in the prediction row, or edit the sample, then accept to record a reviewer modification.</p>
        </>
      )}
    </div>
  );
}

function RunsList({ runs }: { runs: PredictionRun[] }) {
  const selection = useEditor((s) => s.selection);
  const view = useEditor((s) => s.view);
  const qc = useQueryClient();
  const st = useEditor.getState;
  if (!runs.length) return null;
  return (
    <div className="border-t border-slate-200">
      <div className="panel-title">Prediction runs</div>
      <ul className="p-1" data-testid="runs-list">
        {runs.map((r) => (
          <li key={r.id} className="mb-1 rounded border border-slate-200 p-1 text-2xs">
            <div className="font-semibold">
              {r.algorithm} <span className="font-normal text-slate-500">@{r.algorithm_version}</span>
              {r.experimental && <span className="ml-1 rounded bg-amber-100 px-1 text-amber-800">experimental</span>}
            </div>
            <div className="text-slate-600">
              lead {r.lead ?? 'all'} · [{r.start_sample}, {r.end_sample}) ·{' '}
              {Object.entries(r.counts).map(([k, v]) => `${v} ${k}`).join(', ')}
            </div>
            <div className="mt-0.5 flex gap-1">
              <button
                className="btn py-0"
                data-testid={`accept-range-${r.id}`}
                onClick={async () => {
                  const [a, b] = selection ?? [view.start, view.end];
                  try {
                    const res = await api<{ accepted: Annotation[]; skipped: unknown[] }>(`/prediction-runs/${r.id}/accept-range`, {
                      method: 'POST',
                      json: { start_sample: a, end_sample: b },
                    });
                    st().ingest(res.accepted);
                    st().setStatus(`Accepted ${res.accepted.length} prediction(s) in [${a}, ${b}); ${res.skipped.length} skipped (conflicts with existing/reviewed)`, 'ok');
                    await qc.invalidateQueries({ queryKey: ['runs', r.recording_id] });
                  } catch (e) {
                    st().setStatus(errMsg(e), 'error');
                  }
                }}
              >
                Accept all in {selection ? 'selection' : 'view'}
              </button>
              <button
                className="btn py-0"
                data-testid={`discard-run-${r.id}`}
                onClick={async () => {
                  await api(`/prediction-runs/${r.id}`, { method: 'DELETE' });
                  await qc.invalidateQueries({ queryKey: ['runs', r.recording_id] });
                }}
              >
                Discard run
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function RecordingInfo({ datasets }: { datasets: Dataset[] }) {
  const rec = useEditor((s) => s.recording)!;
  const ds = datasets.find((d) => d.id === rec.dataset_id);
  const meta = rec.meta as { diagnoses?: string[]; rhythm?: string; age?: string; sex?: string };
  return (
    <div className="flex flex-col gap-1 p-2 text-2xs" data-testid="recording-info">
      <div className="text-xs font-semibold">{rec.dataset_id}/{rec.name}</div>
      <div className="font-mono">
        {rec.fs} Hz · {rec.n_samples} samples · {rec.duration_s.toFixed(1)} s · {rec.leads.length} leads ({rec.leads.join(', ')})
      </div>
      <div>units: {rec.units.join(', ')} (source units: {rec.original_units.join(', ') || 'n/a'})</div>
      <div>patient/group: {rec.patient_id ?? 'unknown'}</div>
      {meta.age && <div>age {meta.age} · sex {meta.sex}</div>}
      {meta.rhythm && <div>rhythm (header): {meta.rhythm}</div>}
      {meta.diagnoses && meta.diagnoses.length > 0 && <div>diagnoses: {meta.diagnoses.join(' ')}</div>}
      <div className="truncate font-mono text-slate-500" title={rec.signal_sha256}>signal sha256 {rec.signal_sha256.slice(0, 16)}…</div>
      {ds && (
        <div className="mt-1 rounded bg-slate-50 p-1.5">
          <div className="font-semibold">{ds.name} v{ds.version}</div>
          <div>{ds.license}</div>
          <div className="mt-0.5 text-slate-600">{ds.annotation_semantics}</div>
          <a className="text-blue-700 underline" href={ds.source_url} target="_blank" rel="noreferrer">
            {ds.source_url}
          </a>
          {ds.citation && <div className="mt-0.5 text-slate-500" data-testid="dataset-citation">Cite: {ds.citation}</div>}
        </div>
      )}
      <p className="mt-1 text-slate-500">Select an annotation (click it in a tier) to edit label, boundaries and attributes.</p>
    </div>
  );
}

function Shortcuts() {
  const rows: [string, string][] = [
    ['Ctrl+S', 'save (atomic batch)'],
    ['Ctrl+Z / Ctrl+Shift+Z, Ctrl+Y', 'undo / redo'],
    ['Del', 'delete selected'],
    ['+ / −, wheel', 'zoom at cursor'],
    ['Shift+wheel, middle-drag', 'pan'],
    ['[ / ]', 'previous / next beat'],
    ['← / →  (Shift ×10)', 'move cursor 1 sample'],
    ['Alt+← / →', 'nudge selected annotation'],
    ['Enter', 'annotate cursor / selection on active tier'],
    ['A / V', 'annotate / select tool'],
    ['F / Z', 'fit recording / fit selection'],
    ['1–9', 'activate tier'],
  ];
  return (
    <details className="mt-auto border-t border-slate-200 p-2 text-2xs">
      <summary className="cursor-pointer font-semibold text-slate-600">Keyboard shortcuts</summary>
      <table className="mt-1 w-full">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td className="pr-2 font-mono text-slate-700">{k}</td>
              <td className="text-slate-500">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
