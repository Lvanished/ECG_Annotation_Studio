import type { Annotation, BatchOp, Label, Prediction, Tier } from '../api/types';

export type AnnMap = Record<string, Annotation>;

export const isTemp = (id: string) => id.startsWith('tmp-');
let tmpCounter = 0;
export const tempId = () => `tmp-${Date.now().toString(36)}-${(tmpCounter++).toString(36)}`;

const EDIT_FIELDS = [
  'tier',
  'label',
  'lead',
  'start_sample',
  'end_sample',
  'attributes',
  'review_status',
  'beat_id',
  'confidence',
] as const;

export function payload(a: Annotation): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of EDIT_FIELDS) out[f] = a[f];
  return out;
}

function sameEdit(a: Annotation, b: Annotation): boolean {
  return EDIT_FIELDS.every((f) => JSON.stringify(a[f]) === JSON.stringify(b[f]));
}

/** Compute batch operations turning the server state into the working state. */
export function diffOps(server: AnnMap, working: AnnMap): BatchOp[] {
  const ops: BatchOp[] = [];
  for (const [id, w] of Object.entries(working)) {
    const s = server[id];
    if (!s) ops.push({ op: 'create', client_id: id, data: { ...payload(w), source: w.source, provenance: w.provenance } });
    else if (!sameEdit(s, w)) ops.push({ op: 'update', id, revision: s.revision, data: payload(w) });
  }
  for (const [id, s] of Object.entries(server)) {
    if (!working[id]) ops.push({ op: 'delete', id, revision: s.revision });
  }
  return ops;
}

export function reviewedTouched(server: AnnMap, ops: BatchOp[]): string[] {
  return ops
    .filter((o) => o.op !== 'create' && o.id && server[o.id]?.review_status === 'reviewed')
    .map((o) => o.id as string);
}

export function annEnd(a: { start_sample: number; end_sample: number | null }): number {
  return a.end_sample ?? a.start_sample + 1;
}

export function visibleOnLead(a: { lead: string | null }, lead: string | null): boolean {
  return a.lead === null || lead === null || a.lead === lead;
}

/** Client-side mirror of the server overlap policy (server remains authoritative). */
export function overlapConflict(anns: Annotation[], tier: Tier | undefined, cand: Annotation): Annotation | null {
  if (!tier || cand.end_sample === null) return null;
  if (tier.overlap_policy === 'allow') return null;
  for (const a of anns) {
    if (a.id === cand.id || a.tier !== cand.tier || a.end_sample === null || a.lead !== cand.lead) continue;
    if (tier.overlap_policy === 'forbid_same_label' && a.label !== cand.label) continue;
    if (a.start_sample < cand.end_sample && cand.start_sample < a.end_sample) return a;
  }
  return null;
}

export function labelsForTier(labels: Label[], tier: Tier | undefined, kind: 'point' | 'interval' | null): Label[] {
  if (!tier) return [];
  return labels.filter(
    (l) =>
      l.active &&
      l.geometry !== 'relation' &&
      (l.tiers.length === 0 ? tier.allow_free_labels : l.tiers.includes(tier.name)) &&
      (kind === null || l.geometry === 'any' || l.geometry === kind),
  );
}

export function tierAccepts(tier: Tier | undefined, kind: 'point' | 'interval'): boolean {
  return !!tier && (tier.kind === 'mixed' || tier.kind === kind);
}

/** Beat anchors for next/previous navigation (sorted unique sample indices). */
export function beatAnchors(anns: Annotation[], preds: Prediction[], lead: string | null): number[] {
  const set = new Set<number>();
  for (const a of anns) {
    if (!visibleOnLead(a, lead)) continue;
    if (a.kind === 'point' && (a.label === 'R_peak' || a.tier === 'Beat')) set.add(a.start_sample);
  }
  if (set.size === 0) {
    for (const a of anns) {
      if (visibleOnLead(a, lead) && a.label === 'QRS_complex' && a.end_sample !== null)
        set.add(Math.floor((a.start_sample + a.end_sample - 1) / 2));
    }
  }
  for (const p of preds) if (p.status === 'pending' && p.label === 'R_peak') set.add(p.start_sample);
  return [...set].sort((x, y) => x - y);
}

export function nextAnchor(anchors: number[], from: number, dir: 1 | -1): number | null {
  if (dir > 0) {
    for (const a of anchors) if (a > from) return a;
    return null;
  }
  for (let i = anchors.length - 1; i >= 0; i--) if (anchors[i] < from) return anchors[i];
  return null;
}
