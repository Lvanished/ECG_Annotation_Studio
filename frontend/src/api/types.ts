export type Kind = 'point' | 'interval';
export type ReviewStatus = 'draft' | 'needs_review' | 'reviewed' | 'rejected';

export interface Dataset {
  id: string;
  name: string;
  version: string;
  license: string;
  source_url: string;
  citation: string;
  description: string;
  annotation_semantics: string;
  registered: boolean;
  recording_count: number;
  local_records: string[];
  bundled_records: string[];
}

export interface Recording {
  id: string;
  dataset_id: string | null;
  name: string;
  fs: number;
  n_samples: number;
  leads: string[];
  units: string[];
  original_units: string[];
  gains: number[];
  patient_id: string | null;
  meta: Record<string, unknown>;
  source: string;
  signal_sha256: string;
  duration_s: number;
  annotation_count: number;
}

export interface Tier {
  id: string;
  name: string;
  kind: 'point' | 'interval' | 'mixed';
  scope: 'lead' | 'global';
  color: string;
  level: string;
  overlap_policy: string;
  allow_free_labels: boolean;
  order: number;
  is_custom: boolean;
  description: string;
}

export interface AttrSpec {
  type: 'enum' | 'string' | 'number' | 'boolean';
  values?: string[];
  min?: number;
  max?: number;
}

export interface Label {
  code: string;
  name: string;
  level: string;
  parent_code: string | null;
  geometry: 'point' | 'interval' | 'any' | 'relation';
  tiers: string[];
  attributes_schema: Record<string, AttrSpec>;
  description: string;
  is_custom: boolean;
  active: boolean;
  added_in_version: string;
}

export interface Ontology {
  version: string;
  morphology_values: string[];
  tiers: Tier[];
  labels: Label[];
}

export interface Annotation {
  id: string;
  recording_id: string;
  tier: string;
  label: string;
  lead: string | null;
  kind: Kind;
  start_sample: number;
  end_sample: number | null;
  attributes: Record<string, unknown>;
  source: string;
  provenance: Record<string, unknown>;
  review_status: ReviewStatus;
  confidence: number | null;
  beat_id: string | null;
  ontology_version: string;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface BatchOp {
  op: 'create' | 'update' | 'delete';
  id?: string;
  revision?: number;
  client_id?: string;
  data?: Record<string, unknown>;
  confirm_reviewed_change?: boolean;
}

export interface BatchResult {
  batch_id: string;
  created: Annotation[];
  updated: Annotation[];
  deleted: string[];
  id_map: Record<string, string>;
}

export interface Prediction {
  id: string;
  run_id: string;
  recording_id: string;
  tier: string;
  label: string;
  lead: string | null;
  kind: Kind;
  start_sample: number;
  end_sample: number | null;
  confidence: number | null;
  attributes: Record<string, unknown>;
  status: 'pending' | 'accepted' | 'modified' | 'rejected';
  annotation_id: string | null;
}

export interface PredictionRun {
  id: string;
  recording_id: string;
  algorithm: string;
  algorithm_version: string;
  parameters: Record<string, unknown>;
  lead: string | null;
  start_sample: number;
  end_sample: number;
  experimental: boolean;
  created_at: string;
  counts: Record<string, number>;
  n_predictions: number;
  predictions: Prediction[];
}

export interface MeasurementValue {
  name: string;
  value: number | null;
  unit: string;
  samples: number[];
  annotation_ids: string[];
  method: string;
  experimental: boolean;
  reason: string | null;
}

export interface MeasurementResult {
  lead: string | null;
  fs: number;
  anchor: string | null;
  beats: { r_sample: number; anchor: string; anchor_id: string; values: MeasurementValue[] }[];
  summary: Record<string, { unit: string; n: number; mean: number; median: number; std: number; min: number; max: number }>;
}

export interface Snapshot {
  id: string;
  version: string;
  name: string;
  ontology_version: string;
  created_at: string;
  archive_sha256: string;
  recordings: { id: string; name: string; dataset_id: string; split: string; n_annotations: number; patient_id: string | null }[];
  label_statistics: { total?: number; by_source?: Record<string, number>; by_tier_label?: Record<string, number> };
  splits: { leakage_check?: string; recordings?: Record<string, string[]> };
  download_url: string;
}

export interface ImportReport {
  mode: string;
  dataset_version: string;
  ok: boolean;
  recordings: {
    name: string;
    n_exported: number;
    n_matched?: number;
    mismatches?: unknown[];
    new_recording_id?: string;
    new_recording_name?: string;
    signal_identical_to_source?: boolean | null;
    signal_sha256_match?: boolean;
    error?: string;
  }[];
}

export interface Chunk {
  start: number;
  end: number;
  bucket: number;
  index: number;
  fs: number;
  leads: Record<string, { values?: number[]; min?: number[]; max?: number[] }>;
}
