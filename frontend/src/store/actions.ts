import { api, ApiError, errMsg } from '../api/client';
import type { Annotation, BatchResult, Ontology, Prediction } from '../api/types';
import { diffOps, overlapConflict, reviewedTouched, tempId, tierAccepts } from '../lib/annotations';
import { useEditor } from './editor';

export function makeAnnotation(
  onto: Ontology,
  tierName: string,
  start: number,
  end: number | null,
  label?: string,
): Annotation | string {
  const st = useEditor.getState();
  const rec = st.recording;
  if (!rec) return 'No recording loaded';
  const tier = onto.tiers.find((t) => t.name === tierName);
  const kind = end === null ? 'point' : 'interval';
  if (!tier) return `Unknown tier ${tierName}`;
  if (!tierAccepts(tier, kind)) return `Tier "${tier.name}" accepts only ${tier.kind} annotations`;
  const lab = label ?? st.activeLabels[tier.name] ?? '';
  if (!lab) return `Choose a label for tier "${tier.name}"`;
  const lead = tier.scope === 'global' ? null : st.annotationLead;
  const now = new Date().toISOString();
  return {
    id: tempId(),
    recording_id: rec.id,
    tier: tier.name,
    label: lab,
    lead,
    kind,
    start_sample: Math.max(0, Math.min(rec.n_samples - 1, Math.round(start))),
    end_sample: end === null ? null : Math.max(1, Math.min(rec.n_samples, Math.round(end))),
    attributes: {},
    source: 'manual',
    provenance: {},
    review_status: 'draft',
    confidence: null,
    beat_id: null,
    ontology_version: onto.version,
    revision: 0,
    created_at: now,
    updated_at: now,
  };
}

export function addAnnotation(onto: Ontology, tierName: string, start: number, end: number | null): Annotation | null {
  const st = useEditor.getState();
  const a = makeAnnotation(onto, tierName, start, end);
  if (typeof a === 'string') {
    st.setStatus(a, 'error');
    return null;
  }
  if (a.end_sample !== null && a.end_sample <= a.start_sample) {
    st.setStatus('Interval must span at least one sample', 'error');
    return null;
  }
  const tier = onto.tiers.find((t) => t.name === a.tier);
  const clash = overlapConflict(Object.values(st.working), tier, a);
  if (clash) {
    st.setStatus(
      `Overlaps ${clash.label} [${clash.start_sample}, ${clash.end_sample}) - tier policy ${tier?.overlap_policy}`,
      'error',
    );
    return null;
  }
  st.commit((w) => ({ ...w, [a.id]: a }));
  st.select(a.id);
  st.setStatus(
    `Added ${a.label} ${a.end_sample === null ? `@ ${a.start_sample}` : `[${a.start_sample}, ${a.end_sample})`} (unsaved)`,
  );
  return a;
}

export function updateAnnotation(id: string, patch: Partial<Annotation>): void {
  const st = useEditor.getState();
  const cur = st.working[id];
  if (!cur) return;
  st.commit((w) => ({ ...w, [id]: { ...cur, ...patch } }));
}

export function deleteSelected(): void {
  const st = useEditor.getState();
  const id = st.selectedId;
  if (!id || !st.working[id]) return;
  const a = st.working[id];
  st.commit((w) => {
    const next = { ...w };
    delete next[id];
    return next;
  });
  st.select(null);
  st.setStatus(`Deleted ${a.label} @ ${a.start_sample} (unsaved; Ctrl+Z to undo)`);
}

export async function save(confirmFn: (msg: string) => boolean = (m) => window.confirm(m)): Promise<boolean> {
  const st = useEditor.getState();
  const rec = st.recording;
  if (!rec) return false;
  const ops = diffOps(st.server, st.working);
  if (!ops.length) {
    st.setStatus('Nothing to save', 'info');
    return true;
  }
  const reviewed = reviewedTouched(st.server, ops);
  if (reviewed.length) {
    const ok = confirmFn(
      `${reviewed.length} expert-reviewed annotation(s) will be modified or deleted. ` +
        'Previous versions stay in the revision history. Continue?',
    );
    if (!ok) {
      st.setStatus('Save cancelled', 'info');
      return false;
    }
    for (const o of ops) if (o.id && reviewed.includes(o.id)) o.confirm_reviewed_change = true;
  }
  try {
    const res = await api<BatchResult>(`/recordings/${rec.id}/annotations/batch`, {
      method: 'POST',
      json: { operations: ops },
    });
    useEditor.getState().applySave(res);
    useEditor
      .getState()
      .setStatus(
        `Saved: ${res.created.length} created, ${res.updated.length} updated, ${res.deleted.length} deleted (batch ${res.batch_id.slice(0, 8)})`,
        'ok',
      );
    return true;
  } catch (e) {
    const detail = e instanceof ApiError ? (e.detail as { annotation_ids?: string[]; op_index?: number }) : undefined;
    const bad = detail?.annotation_ids?.find((id) => st.working[id]);
    if (bad) st.select(bad);
    else if (detail?.op_index !== undefined) {
      const op = ops[detail.op_index];
      const id = op?.id ?? op?.client_id;
      if (id && st.working[id]) st.select(id);
    }
    st.setStatus(`Save failed (nothing was written): ${errMsg(e)}`, 'error');
    return false;
  }
}

export async function acceptPrediction(p: Prediction, start?: number): Promise<Annotation | null> {
  const st = useEditor.getState();
  try {
    const res = await api<{ annotation: Annotation }>(`/predictions/${p.id}/accept`, {
      method: 'POST',
      json: start !== undefined && start !== p.start_sample ? { start_sample: start } : {},
    });
    st.ingest([res.annotation]);
    st.editPrediction(p.id, null);
    st.setStatus(
      `Prediction ${start !== undefined && start !== p.start_sample ? 'modified and accepted' : 'accepted'} -> ${res.annotation.label} @ ${res.annotation.start_sample}`,
      'ok',
    );
    return res.annotation;
  } catch (e) {
    st.setStatus(`Accept failed: ${errMsg(e)}`, 'error');
    return null;
  }
}
