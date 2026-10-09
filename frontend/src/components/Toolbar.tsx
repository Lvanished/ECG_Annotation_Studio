import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, errMsg } from '../api/client';
import type { Dataset, Ontology, PredictionRun, Recording } from '../api/types';
import { labelsForTier } from '../lib/annotations';
import { dirtyCount, useEditor } from '../store/editor';
import { save } from '../store/actions';
import { goBeat } from '../hooks/useKeyboard';

interface Props {
  datasets: Dataset[];
  recordings: Recording[];
  onto: Ontology;
  datasetId: string;
  setDatasetId: (id: string) => void;
  onSelectRecording: (id: string) => void;
  onExport: () => void;
  onNewTier: () => void;
  runs: PredictionRun[];
}

export function Toolbar({ datasets, recordings, onto, datasetId, setDatasetId, onSelectRecording, onExport, onNewTier }: Props) {
  const rec = useEditor((s) => s.recording);
  const displayLeads = useEditor((s) => s.displayLeads);
  const annotationLead = useEditor((s) => s.annotationLead);
  const tool = useEditor((s) => s.tool);
  const activeTier = useEditor((s) => s.activeTier);
  const activeLabels = useEditor((s) => s.activeLabels);
  const view = useEditor((s) => s.view);
  const selection = useEditor((s) => s.selection);
  const mvPerStrip = useEditor((s) => s.mvPerStrip);
  const dirty = useEditor((s) => dirtyCount(s.server, s.working));
  const canUndo = useEditor((s) => s.undoStack.length > 0);
  const canRedo = useEditor((s) => s.redoStack.length > 0);
  const st = useEditor.getState;
  const qc = useQueryClient();
  const [leadMenu, setLeadMenu] = useState(false);
  const [autoMenu, setAutoMenu] = useState(false);
  const [busy, setBusy] = useState(false);
  const [algo, setAlgo] = useState<'scipy_pan_tompkins' | 'wfdb_xqrs'>('scipy_pan_tompkins');
  const [goStart, setGoStart] = useState('');
  const [goEnd, setGoEnd] = useState('');

  const tier = onto.tiers.find((t) => t.name === activeTier);
  const labels = labelsForTier(onto.labels, tier, tier?.kind === 'point' ? 'point' : tier?.kind === 'interval' ? 'interval' : null);
  const recs = recordings.filter((r) => !datasetId || r.dataset_id === datasetId);

  const runAuto = async (kind: 'detect' | 'segment' | 'delineate', whole: boolean) => {
    if (!rec) return;
    setBusy(true);
    setAutoMenu(false);
    try {
      const range = whole ? {} : { start_sample: view.start, end_sample: view.end };
      const lead = annotationLead ?? displayLeads[0];
      let run: PredictionRun;
      if (kind === 'detect')
        run = await api<PredictionRun>(`/recordings/${rec.id}/detect-r`, { method: 'POST', json: { lead, algorithm: algo, ...range } });
      else if (kind === 'delineate')
        run = await api<PredictionRun>(`/recordings/${rec.id}/delineate`, { method: 'POST', json: { lead, ...range } });
      else {
        const runs = await api<PredictionRun[]>(`/recordings/${rec.id}/prediction-runs`);
        const src = [...runs].reverse().find((r) => r.algorithm.includes('pan_tompkins') || r.algorithm.includes('xqrs'));
        run = await api<PredictionRun>(`/recordings/${rec.id}/segment-beats`, {
          method: 'POST',
          json: src ? { source_run_id: src.id } : { lead },
        });
      }
      await qc.invalidateQueries({ queryKey: ['runs', rec.id] });
      st().setStatus(
        `${run.algorithm}@${run.algorithm_version}: ${run.n_predictions} predictions on ${run.lead ?? 'all leads'}${run.experimental ? ' (EXPERIMENTAL)' : ''} - review in the prediction layer`,
        'ok',
      );
    } catch (e) {
      st().setStatus(`Auto-annotation failed: ${errMsg(e)}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <header className="flex flex-wrap items-center gap-1.5 border-b border-slate-300 bg-white px-2 py-1.5 shadow-sm">
      <div className="mr-2 text-sm font-bold text-slate-800">
        ECG <span className="font-normal text-blue-700">Annotation Studio</span>
      </div>
      <select className="inp" value={datasetId} onChange={(e) => setDatasetId(e.target.value)} data-testid="dataset-select" title="Dataset">
        <option value="">All datasets</option>
        {datasets.filter((d) => d.recording_count > 0).map((d) => (
          <option key={d.id} value={d.id}>
            {d.id.toUpperCase()} ({d.recording_count})
          </option>
        ))}
      </select>
      <select className="inp max-w-[220px]" value={rec?.id ?? ''} onChange={(e) => onSelectRecording(e.target.value)} data-testid="recording-select" title="Recording">
        <option value="">Select recording…</option>
        {recs.map((r) => (
          <option key={r.id} value={r.id}>
            {r.dataset_id}/{r.name} · {r.leads.length}L · {r.fs}Hz · {r.duration_s.toFixed(0)}s
          </option>
        ))}
      </select>
      {rec && (
        <>
          <div className="relative">
            <button className="btn" onClick={() => setLeadMenu((v) => !v)} data-testid="leads-button">
              Leads: {displayLeads.length === rec.leads.length ? `all ${rec.leads.length}` : displayLeads.join(',')} ▾
            </button>
            {leadMenu && (
              <div className="absolute z-30 mt-1 w-44 rounded border border-slate-300 bg-white p-2 shadow-lg" onMouseLeave={() => setLeadMenu(false)}>
                <div className="mb-1 flex gap-1">
                  <button className="btn py-0" onClick={() => st().setDisplayLeads([...rec.leads])} data-testid="leads-all">All</button>
                  <button className="btn py-0" onClick={() => st().setDisplayLeads([annotationLead ?? rec.leads[0]])} data-testid="leads-single">Single</button>
                </div>
                {rec.leads.map((l) => (
                  <label key={l} className="flex items-center gap-1 py-0.5">
                    <input
                      type="checkbox"
                      data-testid={`lead-toggle-${l}`}
                      checked={displayLeads.includes(l)}
                      onChange={(e) => {
                        const next = e.target.checked ? rec.leads.filter((x) => x === l || displayLeads.includes(x)) : displayLeads.filter((x) => x !== l);
                        if (next.length) st().setDisplayLeads(next);
                      }}
                    />
                    {l}
                  </label>
                ))}
              </div>
            )}
          </div>
          <label className="flex items-center gap-1" title="Lead that new annotations are attached to; tiers show this lead plus global annotations">
            <span className="lbl">Annot. lead</span>
            <select
              className="inp"
              data-testid="annotation-lead"
              value={annotationLead ?? ''}
              onChange={(e) => {
                const l = e.target.value || null;
                st().setAnnotationLead(l);
                if (l && !displayLeads.includes(l)) st().setDisplayLeads(rec.leads.filter((x) => x === l || displayLeads.includes(x)));
              }}
            >
              {rec.leads.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
              <option value="">(all / global)</option>
            </select>
          </label>
          <select className="inp" value={mvPerStrip} onChange={(e) => st().setMvPerStrip(Number(e.target.value))} title="Amplitude scale (mV per lead strip)">
            {[1, 1.5, 2, 2.5, 3, 5, 8, 12].map((v) => (
              <option key={v} value={v}>{v} mV/strip</option>
            ))}
          </select>
          <span className="mx-1 h-5 w-px bg-slate-300" />
          <div className="flex">
            <button className={`btn rounded-r-none ${tool === 'select' ? 'btn-active' : ''}`} onClick={() => st().setTool('select')} title="Select / cursor (V)" data-testid="tool-select">
              Select
            </button>
            <button className={`btn rounded-l-none ${tool === 'annotate' ? 'btn-active' : ''}`} onClick={() => st().setTool('annotate')} title="Annotate: click = point, drag = interval (A)" data-testid="tool-annotate">
              Annotate
            </button>
          </div>
          <select className="inp" value={activeTier} onChange={(e) => st().setActiveTier(e.target.value)} data-testid="active-tier" title="Active tier">
            {[...onto.tiers].sort((a, b) => a.order - b.order).map((t) => (
              <option key={t.id} value={t.name}>{t.name}</option>
            ))}
          </select>
          {tier?.allow_free_labels ? (
            <>
              <input
                className="inp w-[130px]"
                list="free-labels"
                placeholder="label (free text)"
                value={activeLabels[activeTier] ?? ''}
                onChange={(e) => st().setActiveLabel(activeTier, e.target.value.trim())}
                data-testid="active-label-free"
                title="Free-text label for this custom tier"
              />
              <datalist id="free-labels">
                {labels.map((l) => (
                  <option key={l.code} value={l.code} />
                ))}
              </datalist>
            </>
          ) : (
            <select
              className="inp"
              value={activeLabels[activeTier] ?? ''}
              onChange={(e) => st().setActiveLabel(activeTier, e.target.value)}
              data-testid="active-label"
              title="Label for new annotations on the active tier"
            >
              {!labels.some((l) => l.code === activeLabels[activeTier]) && <option value={activeLabels[activeTier] ?? ''}>{activeLabels[activeTier] ?? '—'}</option>}
              {labels.map((l) => (
                <option key={l.code} value={l.code}>{l.code}</option>
              ))}
            </select>
          )}
          <button className="btn" onClick={onNewTier} title="Create a custom tier" data-testid="new-tier">+ Tier</button>
          <span className="mx-1 h-5 w-px bg-slate-300" />
          <button className="btn" onClick={() => st().zoom(1 / 1.5)} title="Zoom in (+)" data-testid="zoom-in">＋</button>
          <button className="btn" onClick={() => st().zoom(1.5)} title="Zoom out (−)" data-testid="zoom-out">－</button>
          <button className="btn" onClick={() => st().setView(0, rec.n_samples)} title="Fit recording (F)" data-testid="fit-all">Fit</button>
          <button className="btn" disabled={!selection} onClick={() => selection && st().setView(selection[0], selection[1])} title="Fit selection (Z)">Fit sel.</button>
          <button className="btn" onClick={() => goBeat(-1)} title="Previous beat ([)" data-testid="prev-beat">◀ beat</button>
          <button className="btn" onClick={() => goBeat(1)} title="Next beat (])" data-testid="next-beat">beat ▶</button>
          <form
            className="flex items-center gap-0.5"
            onSubmit={(e) => {
              e.preventDefault();
              const a = parseInt(goStart, 10);
              const b = parseInt(goEnd, 10);
              if (Number.isFinite(a) && Number.isFinite(b) && b > a) st().setView(a, b);
            }}
          >
            <input className="inp w-[68px]" placeholder="start" value={goStart} onChange={(e) => setGoStart(e.target.value)} data-testid="view-start" />
            <input className="inp w-[68px]" placeholder="end" value={goEnd} onChange={(e) => setGoEnd(e.target.value)} data-testid="view-end" />
            <button className="btn" type="submit" data-testid="view-go">Go</button>
          </form>
          <span className="mx-1 h-5 w-px bg-slate-300" />
          <button className="btn" disabled={!canUndo} onClick={() => st().undo()} title="Undo (Ctrl+Z)" data-testid="undo">↶ Undo</button>
          <button className="btn" disabled={!canRedo} onClick={() => st().redo()} title="Redo (Ctrl+Shift+Z / Ctrl+Y)" data-testid="redo">↷ Redo</button>
          <button className={`btn ${dirty ? 'btn-primary' : ''}`} onClick={() => save()} title="Save (Ctrl+S)" data-testid="save">
            Save{dirty ? ` (${dirty})` : ''}
          </button>
          <div className="relative">
            <button className="btn" disabled={busy} onClick={() => setAutoMenu((v) => !v)} data-testid="auto-menu">
              {busy ? 'Running…' : 'Auto-annotate ▾'}
            </button>
            {autoMenu && (
              <div className="absolute right-0 z-30 mt-1 w-72 rounded border border-slate-300 bg-white p-2 shadow-lg" onMouseLeave={() => setAutoMenu(false)}>
                <div className="lbl mb-1">R-peak detection (lead {annotationLead ?? displayLeads[0]})</div>
                <select className="inp mb-1 w-full" value={algo} onChange={(e) => setAlgo(e.target.value as typeof algo)}>
                  <option value="scipy_pan_tompkins">SciPy Pan-Tompkins (adaptive)</option>
                  <option value="wfdb_xqrs">WFDB XQRS</option>
                </select>
                <div className="mb-2 flex gap-1">
                  <button className="btn" onClick={() => runAuto('detect', false)} data-testid="detect-view">Detect in view</button>
                  <button className="btn" onClick={() => runAuto('detect', true)} data-testid="detect-all">Whole recording</button>
                </div>
                <div className="lbl mb-1">Beat segmentation</div>
                <button className="btn mb-2" onClick={() => runAuto('segment', true)} data-testid="segment-beats">Segment beats from latest R-peak run</button>
                <div className="lbl mb-1 text-amber-700">P/QRS/T delineation — experimental</div>
                <p className="mb-1 text-2xs text-amber-700">Heuristic search; not clinically validated. Review every boundary.</p>
                <button className="btn" onClick={() => runAuto('delineate', false)} data-testid="delineate-view">Delineate in view</button>
              </div>
            )}
          </div>
          <button className="btn" onClick={onExport} data-testid="export-button">Export / Import</button>
        </>
      )}
    </header>
  );
}
