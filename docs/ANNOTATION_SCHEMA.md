# Annotation schema

## Coordinates

* All positions are **integer sample indices** of the recording (0-based).
* Intervals are **half-open** `[start_sample, end_sample)`:
  `end_sample` is the first sample *after* the wave; duration =
  `(end - start) / fs`; `0 <= start < end <= n_samples`.
* Points have `end_sample = null`; `0 <= start < n_samples`.
* Time in seconds is derived (`sample / fs`) and never stored as a primary key.
* Datasets that mark inclusive offsets (LUDB, QTDB `)` marks) are converted
  with `end = offset + 1`.

## Annotation record

| field | type | meaning |
|---|---|---|
| `id` | UUID | stable identity |
| `recording_id` | UUID | owning recording |
| `tier` | string | tier name (must exist) |
| `label` | string | ontology code (or free text on free-label tiers) |
| `lead` | string \| null | lead name; `null` = global (all leads) |
| `kind` | `point` \| `interval` | derived from `end_sample` |
| `start_sample`, `end_sample` | int, int \| null | see above |
| `attributes` | object | validated against the label's attribute schema |
| `source` | `manual` \| `reference` \| `algorithm` \| `imported` | origin |
| `provenance` | object | dataset file and annotator, or algorithm run/version/parameters, or import origin |
| `review_status` | `draft` \| `needs_review` \| `reviewed` \| `rejected` | review state |
| `confidence` | float \| null | optional |
| `beat_id` | string \| null | beat grouping (see below) |
| `ontology_version` | string | ontology version at creation/last edit |
| `revision` | int ≥ 1 | incremented on every update/delete |
| `deleted` | bool | soft delete (history is kept) |

Attributes common to every label: `note` (string), `uncertain` (boolean),
`original_symbol` (string). Wave and beat labels add `morphology`
(enum: positive, negative, biphasic, notched, fragmented, double_peak,
R_prime, S_prime, flat, uncertain); rhythm labels add `original_aux`;
quality labels add `severity` (low/moderate/severe); interpretation labels add
`confidence` (low/medium/high). Keys prefixed `x_` are accepted as custom
extension attributes; any other unknown key is rejected.

## Tiers

| tier | kind | scope | level | overlap policy |
|---|---|---|---|---|
| Rhythm | interval | global | L1 | forbid_same_lead |
| Beat | mixed | global | L2 | forbid_same_lead |
| P Wave, QRS Complex, ST Segment, T Wave, PR Segment, U Wave | interval | lead | L3 | forbid_same_lead |
| Fiducial Points | point | lead | L4 | allow |
| Morphology | interval | lead | L5 | allow |
| Signal Quality | interval | lead | L0 | forbid_same_lead |
| Interpretation | interval | global | L7 | allow |

* `forbid_same_lead`: no two intervals of the tier may overlap on the same
  lead (global annotations form their own group). `forbid_same_label`: only
  intervals with the same label may not overlap. `allow`: no restriction.
  Touching intervals (`a.end == b.start`) never overlap.
* Two points with the same label at the same sample on the same tier/lead are
  always rejected (`409 duplicate_point`).
* Custom tiers (`POST /tiers`) choose kind, scope, colour, level, policy and
  `allow_free_labels`. On a free-label tier, labels that are **not** in the
  ontology are accepted as free text; ontology labels keep their tier binding
  (e.g. `motion_artifact` stays restricted to *Signal Quality*).

## Ontology L0–L7

Stored in `ontology_labels` (code, name, level, parent, geometry, allowed
tiers, attribute schema). Seeded from `backend/app/ontology.py`; extensible
through `POST /ontology/labels`. Every ontology change (new label, new or
deleted tier, overlap-policy or free-label change) bumps the patch version (1.0.0 → 1.0.1 …); the version is stamped on
annotations and snapshots.

| level | content | examples |
|---|---|---|
| L0 | signal metadata and quality | good_quality, noise → baseline_wander / muscle_artifact / motion_artifact / powerline_interference, missing_data → lead_off, saturation, unreadable |
| L1 | rhythm episodes | sinus_rhythm, sinus_tachycardia, sinus_bradycardia, atrial_fibrillation, atrial_flutter, ventricular_tachycardia, paced_rhythm, unknown_rhythm, … |
| L2 | beats | normal_beat, LBBB_beat, RBBB_beat, PAC, PVC, fusion_beat, paced_beat, escape beats, unknown_beat, beat_region |
| L3 | wave intervals | P_wave, PR_segment, QRS_complex, ST_segment, T_wave, U_wave |
| L4 | fiducial points | P_onset/peak/offset, QRS_onset, Q_peak, R_peak, S_peak, QRS_offset, J_point, T_onset/peak/offset |
| L5 | morphology | positive, negative, biphasic, notched, fragmented, double_peak, R_prime, S_prime, flat, uncertain_morphology |
| L6 | multi-lead relationships | shared_beat, cross_lead_alignment, lead_specific_boundary, lead_specific_morphology, part_of, global_measurement |
| L7 | research interpretation | conduction_abnormality → first_degree_av_block / RBBB / LBBB / LAFB, repolarization_abnormality, st_t_finding → st_elevation / st_depression / t_wave_inversion, uncertain_finding |

L6 codes are relationship types (`annotation_relationships`: source, target,
`relation_type`, attributes) and cannot be placed on tiers. Validation also
enforces label geometry (point / interval / any) and tier kind.

## Beat grouping

* A `Beat` interval (`beat_region`) uses its own id as `beat_id`.
* Annotations on the other tiers (not Beat, Rhythm, Signal Quality or
  Interpretation) created inside a `Beat` interval on the same lead or a global one gets that
  beat's id automatically.
* Explicit cross-lead links use L6 relationships.

## Revisions, concurrency and review protection

* Create / update / delete each write an `annotation_revisions` row with the
  full annotation snapshot, operation, actor and `batch_id`
  (`GET /annotations/{id}/history`, `GET /recordings/{id}/history`).
* Updates and deletes carry the `revision` the client edited. A stale
  revision returns `409 revision_conflict`.
* Changing or deleting a `reviewed` annotation returns
  `409 reviewed_protected` unless the operation sets
  `confirm_reviewed_change: true` (the UI asks first).
* `POST /recordings/{id}/annotations/batch` applies a list of
  `{op: create|update|delete, id, revision, data, client_id,
  confirm_reviewed_change}` atomically and returns `created`, `updated`,
  `deleted` and `id_map` (client id → server id). Overlap policies are checked
  on the final state of the batch.
* Imported dataset references are stored with `source = reference`,
  `review_status = reviewed`.

## Predictions

Algorithm output is stored separately in `prediction_runs` (algorithm,
version, parameters, lead, window, `experimental`) and `predictions` (same
geometry fields, `status = pending | accepted | modified | rejected`).

* **Accept** creates an annotation with `source = algorithm` and provenance
  `{prediction_id, run_id, algorithm, algorithm_version, parameters,
  experimental, original_start_sample, original_end_sample,
  modified_by_reviewer}`. Accepting with changed boundaries/label marks the
  prediction `modified`.
* Acceptance is refused (`409 conflicts_with_reviewed`) if an annotation with
  the same tier and label is reviewed and overlaps the prediction (points:
  within 50 ms). Equivalent non-reviewed annotations give
  `409 duplicate_annotation`. Reviewed annotations are never overwritten.
* **Accept range** accepts all pending predictions of a run inside a sample
  range and reports the skipped ones with their reason.
