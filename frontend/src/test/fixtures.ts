// Structural fixtures (ontology/recording metadata) for unit tests. They contain
// no ECG samples; signal behaviour is validated against real PhysioNet records
// in the backend and Playwright suites.
import type { Annotation, Label, Ontology, Recording, Tier } from '../api/types';
import { useEditor } from '../store/editor';

const tier = (name: string, kind: Tier['kind'], scope: Tier['scope'], overlap = 'allow', order = 0): Tier => ({
  id: `t-${name}`,
  name,
  kind,
  scope,
  color: '#2563eb',
  level: 'L2',
  overlap_policy: overlap,
  allow_free_labels: false,
  order,
  is_custom: false,
  description: '',
});

const label = (code: string, tiers: string[], geometry: Label['geometry'], schema: Label['attributes_schema'] = {}): Label => ({
  code,
  name: code,
  level: 'L2',
  parent_code: null,
  geometry,
  tiers,
  attributes_schema: schema,
  description: '',
  is_custom: false,
  active: true,
  added_in_version: '1.0.0',
});

export const ONTO: Ontology = {
  version: '1.0.0',
  morphology_values: ['normal', 'notched'],
  tiers: [
    tier('Rhythm', 'interval', 'global', 'forbid_same_lead', 1),
    tier('P Wave', 'interval', 'lead', 'forbid_same_lead', 3),
    tier('QRS Complex', 'interval', 'lead', 'forbid_same_lead', 4),
    tier('Fiducial Points', 'point', 'lead', 'allow', 7),
  ],
  labels: [
    label('sinus_rhythm', ['Rhythm'], 'interval'),
    label('P_wave', ['P Wave'], 'interval', { morphology: { type: 'enum', values: ['normal', 'notched'] } }),
    label('QRS_complex', ['QRS Complex'], 'interval', { morphology: { type: 'enum', values: ['normal', 'notched'] } }),
    label('R_peak', ['Fiducial Points'], 'point'),
    label('P_peak', ['Fiducial Points'], 'point'),
  ],
};

export const REC: Recording = {
  id: 'rec-1',
  dataset_id: 'ludb',
  name: '1',
  fs: 500,
  n_samples: 5000,
  leads: ['I', 'II', 'III'],
  units: ['mV', 'mV', 'mV'],
  original_units: ['mV', 'mV', 'mV'],
  gains: [1, 1, 1],
  patient_id: 'ludb-1',
  meta: {},
  source: 'physionet',
  signal_sha256: 'x',
  duration_s: 10,
  annotation_count: 0,
};

export function ann(id: string, p: Partial<Annotation>): Annotation {
  return {
    id,
    recording_id: REC.id,
    tier: 'Fiducial Points',
    label: 'R_peak',
    lead: 'II',
    kind: 'point',
    start_sample: 0,
    end_sample: null,
    attributes: {},
    source: 'manual',
    provenance: {},
    review_status: 'draft',
    confidence: null,
    beat_id: null,
    ontology_version: '1.0.0',
    revision: 1,
    created_at: '',
    updated_at: '',
    ...p,
  };
}

export function resetEditor(anns: Annotation[] = []) {
  const s = useEditor.getState();
  s.setRecording(REC);
  s.loadDocument(anns);
  useEditor.setState({ hiddenTiers: [], collapsedTiers: [], activeTier: 'Fiducial Points', tool: 'select' });
}
