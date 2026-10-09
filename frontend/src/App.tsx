import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, errMsg } from './api/client';
import { fetchAnnotations, useDatasets, useOntology, usePredictionRuns, useRecordings } from './api/queries';
import { WaveformView } from './components/WaveformView';
import { TierPanel } from './components/TierPanel';
import { Toolbar } from './components/Toolbar';
import { PropertiesPanel } from './components/PropertiesPanel';
import { AnalysisPanel } from './components/AnalysisPanel';
import { ExportDialog } from './components/ExportDialog';
import { useKeyboard } from './hooks/useKeyboard';
import { dirtyCount, useEditor } from './store/editor';

function useSplitter(initial: number, min: number, max: number, axis: 'x' | 'y', invert = true) {
  const [size, setSize] = useState(initial);
  const start = useRef<{ p: number; s: number } | null>(null);
  const onPointerDown = (e: React.PointerEvent) => {
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    start.current = { p: axis === 'x' ? e.clientX : e.clientY, s: size };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!start.current) return;
    const d = (axis === 'x' ? e.clientX : e.clientY) - start.current.p;
    setSize(Math.max(min, Math.min(max, start.current.s + (invert ? -d : d))));
  };
  const onPointerUp = () => {
    start.current = null;
  };
  return { size, handlers: { onPointerDown, onPointerMove, onPointerUp } };
}

export default function App() {
  const qc = useQueryClient();
  const datasets = useDatasets();
  const recordings = useRecordings();
  const onto = useOntology();
  const rec = useEditor((s) => s.recording);
  const status = useEditor((s) => s.status);
  const runs = usePredictionRuns(rec?.id);
  const [datasetId, setDatasetId] = useState('');
  const [showExport, setShowExport] = useState(false);
  const [showTier, setShowTier] = useState(false);
  const [importing, setImporting] = useState(false);
  const right = useSplitter(330, 240, 600, 'x');
  const bottom = useSplitter(190, 90, 480, 'y');
  const tiersH = useSplitter(300, 120, 700, 'y');
  const st = useEditor.getState;

  const predictions = useMemo(() => (runs.data ?? []).flatMap((r) => r.predictions), [runs.data]);
  useKeyboard(onto.data, predictions);

  const openRecording = useCallback(
    async (id: string) => {
      const s = st();
      if (dirtyCount(s.server, s.working) > 0 && !window.confirm('Discard unsaved annotation changes?')) return;
      if (!id) {
        s.setRecording(null);
        return;
      }
      try {
        const r = await qc.fetchQuery({ queryKey: ['recording', id], queryFn: () => api<typeof s.recording>(`/recordings/${id}`), staleTime: 0 });
        const anns = await fetchAnnotations(id);
        if (!r) return;
        st().setRecording(r);
        st().loadDocument(anns);
        st().setStatus(`Loaded ${r.dataset_id}/${r.name}: ${r.n_samples} samples @ ${r.fs} Hz, ${r.leads.length} leads, ${anns.length} annotations`, 'ok');
        const url = new URL(window.location.href);
        url.searchParams.set('recording', id);
        window.history.replaceState(null, '', url);
      } catch (e) {
        st().setStatus(`Could not load recording: ${errMsg(e)}`, 'error');
      }
    },
    [qc, st],
  );

  // restore last opened recording after a browser refresh
  useEffect(() => {
    const id = new URL(window.location.href).searchParams.get('recording');
    if (id && recordings.data?.some((r) => r.id === id) && !st().recording) void openRecording(id);
  }, [recordings.data, openRecording, st]);

  const importSamples = async () => {
    setImporting(true);
    try {
      for (const ds of ['ludb', 'qtdb', 'mitdb']) await api(`/datasets/${ds}/import`, { method: 'POST', json: {} });
      await qc.invalidateQueries({ queryKey: ['recordings'] });
      await qc.invalidateQueries({ queryKey: ['datasets'] });
      st().setStatus('Imported bundled PhysioNet samples', 'ok');
    } catch (e) {
      st().setStatus(`Import failed: ${errMsg(e)}`, 'error');
    } finally {
      setImporting(false);
    }
  };

  if (onto.isError || datasets.isError)
    return (
      <div className="p-6 text-sm text-red-700">
        Backend unreachable: {errMsg(onto.error ?? datasets.error)}. Start the API (see README) and reload.
      </div>
    );
  if (!onto.data || !datasets.data || !recordings.data) return <div className="p-6 text-sm text-slate-500">Loading…</div>;

  return (
    <div className="flex h-full flex-col">
      <Toolbar
        datasets={datasets.data}
        recordings={recordings.data}
        onto={onto.data}
        datasetId={datasetId}
        setDatasetId={setDatasetId}
        onSelectRecording={openRecording}
        onExport={() => setShowExport(true)}
        onNewTier={() => setShowTier(true)}
        runs={runs.data ?? []}
      />
      {!rec ? (
        <EmptyState
          hasRecordings={recordings.data.length > 0}
          datasets={datasets.data}
          importing={importing}
          onImport={importSamples}
        />
      ) : (
        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="flex min-h-0 flex-1 flex-col">
              <WaveformView onto={onto.data} predictions={predictions} />
              <div className="h-1.5 shrink-0 cursor-row-resize bg-slate-200 hover:bg-blue-300" {...tiersH.handlers} title="Drag to resize" />
              <div className="flex min-h-[110px] shrink flex-col" style={{ height: tiersH.size }}>
                <TierPanel onto={onto.data} predictions={predictions} />
              </div>
            </div>
            <div className="h-1.5 shrink-0 cursor-row-resize bg-slate-200 hover:bg-blue-300" {...bottom.handlers} title="Drag to resize" />
            <div className="min-h-[80px] shrink" style={{ height: bottom.size }}>
              <AnalysisPanel />
            </div>
          </div>
          <div className="w-1.5 shrink-0 cursor-col-resize bg-slate-200 hover:bg-blue-300" {...right.handlers} title="Drag to resize" />
          <div className="shrink-0 border-l border-slate-200" style={{ width: right.size }}>
            <PropertiesPanel onto={onto.data} runs={runs.data ?? []} datasets={datasets.data} />
          </div>
        </div>
      )}
      <footer
        className={`truncate border-t px-2 py-0.5 text-2xs ${status.kind === 'error' ? 'border-red-300 bg-red-50 text-red-800' : status.kind === 'ok' ? 'border-green-200 bg-green-50 text-green-800' : 'border-slate-200 bg-slate-50 text-slate-600'}`}
        data-testid="status-bar"
      >
        {status.text}
        <span className="float-right text-slate-400">ontology {onto.data.version} · research prototype, not a medical device</span>
      </footer>
      {showExport && rec && <ExportDialog onto={onto.data} onClose={() => setShowExport(false)} onOpenRecording={openRecording} />}
      {showTier && <TierDialog onClose={() => setShowTier(false)} />}
    </div>
  );
}

function EmptyState({ hasRecordings, datasets, importing, onImport }: { hasRecordings: boolean; datasets: { id: string; name: string; version: string; license: string; local_records: string[]; recording_count: number }[]; importing: boolean; onImport: () => void }) {
  return (
    <div className="m-6 max-w-3xl rounded border border-slate-300 bg-white p-4 text-xs" data-testid="empty-state">
      <h2 className="mb-2 text-sm font-semibold">{hasRecordings ? 'Select a recording in the toolbar' : 'No recordings registered yet'}</h2>
      <table className="mb-3 w-full">
        <thead>
          <tr className="text-left text-slate-500">
            <th>dataset</th>
            <th>license</th>
            <th>local WFDB records</th>
            <th>registered</th>
          </tr>
        </thead>
        <tbody>
          {datasets.map((d) => (
            <tr key={d.id} className="border-t border-slate-100">
              <td>{d.name} v{d.version}</td>
              <td>{d.license}</td>
              <td>{d.local_records.length}</td>
              <td>{d.recording_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="btn btn-primary" disabled={importing} onClick={onImport} data-testid="import-samples">
        {importing ? 'Importing…' : 'Register local PhysioNet records (data/physionet)'}
      </button>
      <p className="mt-2 text-slate-500">
        Download more with <code>python scripts/download_datasets.py --dataset ludb --records 7 8 9</code>. All files are SHA-256 verified against PhysioNet.
      </p>
    </div>
  );
}

function TierDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const [kind, setKind] = useState<'point' | 'interval' | 'mixed'>('interval');
  const [scope, setScope] = useState<'lead' | 'global'>('lead');
  const [color, setColor] = useState('#0ea5e9');
  const [policy, setPolicy] = useState('allow');
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/40 pt-24" onMouseDown={onClose}>
      <form
        className="flex w-96 flex-col gap-2 rounded bg-white p-3 shadow-xl"
        onMouseDown={(e) => e.stopPropagation()}
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api('/tiers', { method: 'POST', json: { name, kind, scope, color, overlap_policy: policy, allow_free_labels: true } });
            await qc.invalidateQueries({ queryKey: ['ontology'] });
            useEditor.getState().setActiveTier(name);
            useEditor.getState().setStatus(`Created tier "${name}" (free-text labels allowed)`, 'ok');
            onClose();
          } catch (ex) {
            setErr(errMsg(ex));
          }
        }}
        data-testid="tier-dialog"
      >
        <h3 className="text-sm font-semibold">New custom tier</h3>
        <input className="inp" placeholder="Tier name" value={name} onChange={(e) => setName(e.target.value)} required data-testid="tier-name-input" />
        <select className="inp" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
          <option value="interval">interval</option>
          <option value="point">point</option>
          <option value="mixed">mixed</option>
        </select>
        <select className="inp" value={scope} onChange={(e) => setScope(e.target.value as typeof scope)}>
          <option value="lead">lead-specific</option>
          <option value="global">global (all leads)</option>
        </select>
        <select className="inp" value={policy} onChange={(e) => setPolicy(e.target.value)}>
          <option value="allow">overlaps allowed</option>
          <option value="forbid_same_lead">no overlap within a lead</option>
          <option value="forbid_same_label">no overlap of same label</option>
        </select>
        <input type="color" value={color} onChange={(e) => setColor(e.target.value)} />
        <p className="text-2xs text-slate-500">Custom tiers accept free-text labels; add ontology labels via POST /ontology/labels for strict validation.</p>
        {err && <p className="text-2xs text-red-700">{err}</p>}
        <div className="flex justify-end gap-1">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" data-testid="tier-create">Create</button>
        </div>
      </form>
    </div>
  );
}
