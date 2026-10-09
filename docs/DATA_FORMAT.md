# Data formats

## Signal storage

* Every recording's samples are stored once as `DATA_DIR/signals/<recording_id>.npy`:
  float32, shape `[n_samples, n_leads]`, **physical units in millivolts**.
  The SHA-256 of the file is kept in `recordings.signal_sha256`.
* Conversion from WFDB: `wfdb.rdrecord` physical signal
  `(digital - baseline) / adc_gain` (verified against the raw ADC formula in
  `test_voltage_conversion_matches_adc_formula`), then unit scaling to mV
  (`mV ×1`, `uV`/`µV ×0.001`, `V ×1000`). Unknown units are rejected; raw ADC
  counts are never treated as mV. WFDB invalid samples (NaN) are zero-filled.
* Lead names are normalised (`i → I`, `avr → aVR`, `v1 → V1`); other names
  (e.g. MIT-BIH `MLII`, `V5`) are kept.
* `recordings` also stores `fs`, `n_samples`, `leads`, `units` (always mV),
  `original_units`, `gains`, `patient_id`, header metadata and the SHA-256 of
  every source file.

## Dataset adapters (PhysioNet, ODC-By 1.0)

| dataset | records | fs | leads | reference annotations → studio |
|---|---|---|---|---|
| LUDB 1.0.1 | 200 × 10 s | 500 Hz | 12 | per-lead `(` onset, `p`/`N`/`t` peak, `)` offset files `.i … .v6` → per-lead P_wave / QRS_complex / T_wave intervals `[onset, offset+1)` plus P_peak / R_peak / T_peak points; incomplete triplets → onset/offset fiducial points only. Header rhythm → one global Rhythm interval. `patient_id = ludb-<n>` |
| QTDB 1.0.0 | 105 × 15 min | 250 Hz | 2 | `.q1c` (cardiologist 1) boundaries for selected beats, judged on both leads → **global** (`lead = null`) intervals and peaks; missing T onsets → T_peak/T_offset points. `.atr` beat labels → Beat points. Automatic `.pu*` files are not imported. `patient_id = qtdb-<record>` |
| MIT-BIH 1.0.0 | 48 × 30 min | 360 Hz | 2 | `.atr` beat symbols at the beat fiducial point → global Beat points (N→normal_beat, V→PVC, …, original symbol kept); `+` rhythm changes → global Rhythm intervals up to the next change. No wave boundaries exist. `patient_id = mitdb-<subject>` (201 and 202 share a subject) |

All reference annotations are imported with `source = reference`,
`review_status = reviewed` and provenance `{dataset, dataset_version, file,
annotator}`.

Bundled in `data/physionet` (6.4 MB, imported automatically in Docker):
LUDB 1–6, QTDB sel100 and sel103, MIT-BIH 100 and 105, each with
`SHA256SUMS.txt` and a `download_manifest.json`. More records:
`scripts/download_datasets.py` or `POST /datasets/{id}/download` (both
verify SHA-256 against PhysioNet's published checksums), then
`POST /datasets/{id}/import`.

## Upload format

`POST /recordings/upload` accepts an `.npz` with:

* `signal`: float array `[n_samples, n_leads]`
* `fs`: scalar sampling frequency (0 < fs ≤ 20000)
* `leads`: string array of length `n_leads`
* `units` (optional, default `mV` for every lead): per-lead `mV`, `uV`, `µV` or `V`

NaN/Inf, wrong shapes, lead-count mismatches and unknown units are rejected
(422). The recording is registered in the dataset `uploads` with
`patient_id = null`.

## Dataset snapshot (export)

`POST /exports` with `{name, version?, recording_ids? | dataset_id?, sources,
review_statuses, mask_tiers, split, seed}` writes
`DATA_DIR/exports/<version>/` and `<version>.zip` (download:
`GET /exports/{version}/download`). The version defaults to
`<name>-v<k>`; an existing version is never overwritten (409). Files are made
read-only and listed with SHA-256 in the manifest; `GET /exports/{version}/verify`
re-hashes them and reports annotations changed since the export.

```
<version>/
  manifest.json      format "ecg-annotation-studio/snapshot-1", dataset_version, ontology_version,
                     params, recordings (id, dataset, name, patient_id, split, fs, n_samples, leads,
                     signal_sha256, signal_file, n_annotations), annotation_revisions {id: revision},
                     label_statistics (by tier::label, by source, by split), splits summary,
                     files {path: sha256}
  annotations.json   full document: ontology (tiers, labels, schemas), and per recording its metadata,
                     split, signal_file, annotations (all fields incl. provenance) and relationships
  annotations.csv    one row per annotation: ids, record, patient, split, tier, label, lead, kind,
                     start_sample, end_sample, start_s, end_s, fs, source, review_status, revision,
                     beat_id, confidence, ontology_version, attributes (JSON), provenance (JSON)
  measurements.csv   per beat and lead: measurement, value, unit, samples, annotation_ids, method,
                     experimental, na_reason
  splits.json        patient-grouped assignment, seed, fractions, leakage_check
  README.txt         short format description
  signals/<dataset>_<record>_<id8>.npz
```

### NPZ per recording

| key | dtype / shape | content |
|---|---|---|
| `signal` | float32 `[n, L]` | samples in mV |
| `fs`, `leads`, `units` | scalar, `[L]`, `[L]` | |
| `label_names` | `[K]` | label vocabulary of this recording |
| `point_sample`, `point_label`, `point_lead` | int64/int32 `[P]` | points (`lead = -1` → global) |
| `interval_start`, `interval_end`, `interval_label`, `interval_lead` | int64/int32 `[I]` | half-open intervals |
| `mask_<tier>` | int16 `[L, n]` | dense segmentation mask (codes below) |
| `multihot_<tier>` | uint8 `[L, n, C]` | every overlapping class kept |
| `uncertain_<tier>` | bool `[L, n]` | samples covered by `uncertain = true` annotations |
| `classes_<tier>` | `[C]` | class names; mask value `k ≥ 1` = `classes[k-1]` |
| `meta_json` | string | recording metadata, split, mask codes, conventions |

`<tier>` is the slug of the tier name (`p_wave`, `qrs_complex`, `t_wave`).

### Segmentation mask codes

| value | meaning |
|---|---|
| `k ≥ 1` | sample belongs to class `classes_<tier>[k-1]` |
| `0` | annotated background: inside the tier's annotated extent on this lead, no label |
| `-1` | unannotated: outside the annotated extent (e.g. unannotated LUDB edge beats, the whole lead if the tier has nothing) |
| `-2` | overlap of different classes |
| `-3` | uncertain (`attributes.uncertain = true`) |

Global annotations (`lead = null`) apply to every lead. Training code should
ignore negative codes; `examples/pytorch_dataset.py` maps them to
`ignore_index = -100`.

### Patient-level split

Recordings are grouped by `patient_id` (or by recording id when the patient
is unknown); whole groups are assigned to train/val/test with a seeded
shuffle and greedy balancing towards the requested fractions. `splits.json`
records the assignment and `leakage_check: passed` only if no patient appears
in two splits.

### Round-trip import

`POST /imports?mode=verify|new_recording` (default `new_recording`;
multipart `file` = snapshot ZIP or `annotations.json`):

* `verify`: compares every exported annotation (tier, label, lead, kind,
  start, end, attributes) with the live database and the signal SHA-256.
* `new_recording`: creates a new recording from the snapshot's NPZ signal
  (or the existing source signal for a bare JSON), imports the annotations
  with `source = imported` and the original id/source/revision/provenance in
  `provenance`, re-reads them and reports any field mismatch.

## Quick export

`GET /recordings/{id}/export?format=json|csv` downloads the current
annotations of one recording (not versioned, not immutable; use snapshots for
training data).

## PyTorch example

`examples/pytorch_dataset.py <snapshot.zip | snapshot dir>` builds a windowed
segmentation `Dataset` (0 background, 1 P, 2 QRS, 3 T, −100 ignored),
checks split leakage and runs a tiny CNN forward/backward pass. It needs
`torch` (not part of the backend requirements).
