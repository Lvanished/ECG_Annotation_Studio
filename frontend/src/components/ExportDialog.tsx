import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, API_BASE, errMsg } from '../api/client';
import { useSnapshots } from '../api/queries';
import type { ImportReport, Ontology, Snapshot } from '../api/types';
import { useEditor } from '../store/editor';

interface Props {
  onto: Ontology;
  onClose: () => void;
  onOpenRecording: (id: string) => void;
}

export function ExportDialog({ onto, onClose, onOpenRecording }: Props) {
  const rec = useEditor((s) => s.recording)!;
  const qc = useQueryClient();
  const snaps = useSnapshots();
  const [name, setName] = useState('ecg-dataset');
  const [version, setVersion] = useState('');
  const [scope, setScope] = useState<'recording' | 'dataset' | 'all'>('recording');
  const [sources, setSources] = useState(['manual', 'reference', 'algorithm', 'imported']);
  const [statuses, setStatuses] = useState(['draft', 'needs_review', 'reviewed']);
  const [maskTiers, setMaskTiers] = useState(['P Wave', 'QRS Complex', 'T Wave']);
  const [split, setSplit] = useState({ train: 0.7, val: 0.15, test: 0.15 });
  const [seed, setSeed] = useState(42);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [created, setCreated] = useState<Snapshot | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [mode, setMode] = useState<'new_recording' | 'verify'>('new_recording');
  const dirty = useEditor((s) => Object.keys(s.working).some((k) => s.working[k] !== s.server[k]) || Object.keys(s.server).some((k) => !s.working[k]));

  const toggle = (arr: string[], v: string, set: (x: string[]) => void) => set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  const create = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const body: Record<string, unknown> = { name, sources, review_statuses: statuses, mask_tiers: maskTiers, split, seed };
      if (version.trim()) body.version = version.trim();
      if (scope === 'recording') body.recording_ids = [rec.id];
      if (scope === 'dataset') body.dataset_id = rec.dataset_id;
      const s = await api<Snapshot>('/exports', { method: 'POST', json: body });
      setCreated(s);
      await qc.invalidateQueries({ queryKey: ['exports'] });
    } catch (e) {
      setMsg(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const doImport = async (file: File) => {
    setBusy(true);
    setReport(null);
    setMsg(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch(`${API_BASE}/imports?mode=${mode}`, { method: 'POST', body: fd });
      const body = await res.json();
      if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail));
      setReport(body as ImportReport);
      await qc.invalidateQueries({ queryKey: ['recordings'] });
    } catch (e) {
      setMsg(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/40 pt-10" onMouseDown={onClose}>
      <div className="max-h-[88vh] w-[880px] overflow-y-auto rounded-md bg-white shadow-xl" onMouseDown={(e) => e.stopPropagation()} data-testid="export-dialog">
        <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
          <h2 className="text-sm font-semibold">Dataset export (immutable snapshot) &amp; round-trip import</h2>
          <button className="btn" onClick={onClose} data-testid="export-close">Close</button>
        </div>
        <div className="grid grid-cols-2 gap-3 p-3">
          <div className="flex flex-col gap-2">
            <div className="lbl">New snapshot</div>
            {dirty && <p className="rounded bg-amber-50 p-1 text-2xs text-amber-800">You have unsaved edits — exports include saved annotations only.</p>}
            <label className="flex items-center gap-2">
              <span className="w-20">Name</span>
              <input className="inp flex-1" value={name} onChange={(e) => setName(e.target.value)} data-testid="export-name" />
            </label>
            <label className="flex items-center gap-2">
              <span className="w-20">Version</span>
              <input className="inp flex-1" placeholder="auto (name-vN)" value={version} onChange={(e) => setVersion(e.target.value)} />
            </label>
            <label className="flex items-center gap-2">
              <span className="w-20">Scope</span>
              <select className="inp flex-1" value={scope} onChange={(e) => setScope(e.target.value as typeof scope)} data-testid="export-scope">
                <option value="recording">Current recording ({rec.name})</option>
                <option value="dataset">Current dataset ({rec.dataset_id})</option>
                <option value="all">All recordings</option>
              </select>
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <span className="w-20">Sources</span>
              {['manual', 'reference', 'algorithm', 'imported'].map((s) => (
                <label key={s} className="flex items-center gap-0.5">
                  <input type="checkbox" checked={sources.includes(s)} onChange={() => toggle(sources, s, setSources)} />
                  {s}
                </label>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="w-20">Review</span>
              {['draft', 'needs_review', 'reviewed', 'rejected'].map((s) => (
                <label key={s} className="flex items-center gap-0.5">
                  <input type="checkbox" checked={statuses.includes(s)} onChange={() => toggle(statuses, s, setStatuses)} />
                  {s}
                </label>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="w-20">Mask tiers</span>
              {onto.tiers.filter((t) => t.kind !== 'point').map((t) => (
                <label key={t.id} className="flex items-center gap-0.5">
                  <input type="checkbox" checked={maskTiers.includes(t.name)} onChange={() => toggle(maskTiers, t.name, setMaskTiers)} />
                  {t.name}
                </label>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <span className="w-20">Split</span>
              {(['train', 'val', 'test'] as const).map((k) => (
                <label key={k} className="flex items-center gap-0.5">
                  {k}
                  <input className="inp w-14" type="number" step="0.05" value={split[k]} onChange={(e) => setSplit({ ...split, [k]: Number(e.target.value) })} />
                </label>
              ))}
              <label className="flex items-center gap-0.5">
                seed <input className="inp w-14" type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
              </label>
            </div>
            <p className="text-2xs text-slate-500">Splits group recordings by patient id; no patient appears in two splits.</p>
            <button className="btn btn-primary self-start" disabled={busy} onClick={create} data-testid="export-create">
              {busy ? 'Working…' : 'Create snapshot'}
            </button>
            {created && (
              <div className="rounded border border-green-300 bg-green-50 p-2 text-2xs" data-testid="export-result">
                <div className="font-semibold">
                  Snapshot <span data-testid="export-version">{created.version}</span> created
                </div>
                <div>ontology {created.ontology_version} · {created.label_statistics.total ?? 0} annotations · {created.recordings.length} recording(s)</div>
                <div>patient leakage check: {created.splits.leakage_check}</div>
                <div className="truncate font-mono">sha256 {created.archive_sha256}</div>
                <a className="btn mt-1" href={`${API_BASE}${created.download_url}`} download data-testid="export-download">
                  Download ZIP
                </a>
              </div>
            )}
            {msg && <p className="rounded bg-red-50 p-1 text-2xs text-red-700" data-testid="export-error">{msg}</p>}
          </div>
          <div className="flex flex-col gap-2">
            <div className="lbl">Import snapshot (round-trip validation)</div>
            <label className="flex items-center gap-2">
              <span>Mode</span>
              <select className="inp" value={mode} onChange={(e) => setMode(e.target.value as typeof mode)} data-testid="import-mode">
                <option value="new_recording">Import into new recording(s)</option>
                <option value="verify">Verify against database (no writes)</option>
              </select>
            </label>
            <input type="file" accept=".zip,.json" data-testid="import-file" onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = '';
                if (f) void doImport(f);
              }}
            />
            {report && (
              <div className={`rounded border p-2 text-2xs ${report.ok ? 'border-green-300 bg-green-50' : 'border-red-300 bg-red-50'}`} data-testid="import-report">
                <div className="font-semibold" data-testid="import-ok">
                  {report.ok ? 'Round trip OK: sample positions and labels identical' : 'Differences found'}
                </div>
                {report.recordings.map((r) => (
                  <div key={r.name} className="mt-1">
                    {r.name}: {r.n_matched ?? 0}/{r.n_exported} identical
                    {r.signal_identical_to_source !== undefined && ` · signal identical: ${String(r.signal_identical_to_source)}`}
                    {r.error && ` · ${r.error}`}
                    {r.new_recording_id && (
                      <button className="btn ml-1 py-0" onClick={() => { onOpenRecording(r.new_recording_id!); onClose(); }} data-testid="open-imported">
                        open {r.new_recording_name}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
            <div className="lbl mt-2">Existing snapshots</div>
            <ul className="max-h-64 overflow-y-auto text-2xs">
              {(snaps.data ?? []).map((s) => (
                <li key={s.id} className="flex items-center gap-1 border-t border-slate-100 py-1">
                  <span className="font-mono font-semibold">{s.version}</span>
                  <span className="text-slate-500">{new Date(s.created_at).toLocaleString()} · {s.label_statistics.total ?? 0} ann.</span>
                  <a className="btn ml-auto py-0" href={`${API_BASE}${s.download_url}`} download>ZIP</a>
                  <button
                    className="btn py-0"
                    onClick={async () => {
                      const v = await api<{ immutable_integrity: string; annotations_changed_since_export: number }>(`/exports/${s.version}/verify`);
                      setMsg(`${s.version}: integrity ${v.immutable_integrity}; ${v.annotations_changed_since_export} annotation(s) changed in DB since export`);
                    }}
                  >
                    Verify
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
