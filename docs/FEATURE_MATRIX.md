# Feature matrix

Status values: **Verified** = implemented and verified by an automated test
or a measured run (named in the evidence column); **Unverified** =
implemented, but only exercised manually or indirectly; **Partial**;
**Not implemented**; **Blocked**.

Test abbreviations: `BE:` backend pytest file, `FE:` Vitest file,
`E2E-acc` = `acceptance.spec.ts`, `E2E-ed` / `E2E-mit` = the two tests in
`editor.spec.ts`, `E2E-an` = `analysis.spec.ts`, `EVAL` = `scripts/evaluate.py`.

## Waveform viewer (task §4.1)

| feature | status | evidence |
|---|---|---|
| Load real ECG signals from the backend | Verified | E2E-acc step 5, BE:test_datasets |
| Render actual sample values (raw at high zoom) | Verified | FE:components (canvas calls), E2E-mit |
| Single lead / multiple synchronised leads / 12 leads | Verified | E2E-acc steps 5–6 |
| Horizontal zoom (buttons, `+`/`-`) and pan (middle drag, Shift+wheel) | Verified (zoom, keys) / Unverified (pan gestures) | E2E-acc step 7, E2E-ed; FE:lib `pan` |
| Mouse-wheel zoom anchored at the cursor | Verified | FE:lib (anchor within one sample), E2E-acc, E2E-mit |
| Drag-based time selection, fit to selection (`z`) | Unverified | code path shared with annotate drag (verified); no dedicated test |
| Sample-exact positioning (integer samples) | Verified | FE:lib mapping, E2E-acc steps 8–15 |
| Voltage in mV (readout, mV scale) | Verified | E2E-acc step 5, E2E-mit |
| ECG paper grid | Verified | FE:lib grid choice; visual check during development |
| Next / previous beat navigation | Verified | E2E-ed (`[`/`]` land on reference R peaks), FE:lib |
| Fit to recording (`f`) | Verified | E2E-ed, E2E-mit |
| Long-record chunk loading (LOD 1024-bucket chunks) | Verified | BE:test_datasets chunk exactness, E2E-mit (30-min record) |
| Min/max envelope rendering for large records | Verified | FE:components, E2E-mit |

## Tier system and editing (task §4.2, §4.3)

| feature | status | evidence |
|---|---|---|
| Default tiers (Rhythm, Beat, P, QRS, ST, T, Fiducial, Morphology, Signal Quality, + PR, U, Interpretation) | Verified | E2E-acc, BE:test_annotations |
| Show / hide tier | Verified | FE:components, E2E-ed |
| Collapse / expand tier | Verified | E2E-ed |
| Point and interval annotations (click / drag / double-click / Enter) | Verified | E2E-acc steps 8–10, FE:components |
| Select, delete | Verified | FE:components, E2E-ed |
| Label and attribute editing (morphology, uncertain, note) | Verified | E2E-acc step 12, FE:components |
| Boundary / point dragging in whole samples | Verified | FE:components, E2E-acc step 11 |
| Alt+Arrow nudging | Verified | E2E-ed |
| Custom tier creation (incl. free-text labels) | Verified | E2E-ed, BE:test_annotations |
| Configurable overlap policies | Verified | BE:test_annotations, FE:editor, E2E-ed |
| Shortcuts: save, delete, undo, redo, zoom, next/prev beat | Verified | E2E-ed |
| Real undo/redo (drag = one step) | Verified | FE:editor, E2E-acc step 11, E2E-ed |
| Exact restore after browser refresh | Verified | E2E-acc steps 14–15 |
| Resizable panels | Unverified | implemented with splitters; used manually |

## Ontology and data model (task §5, §6)

| feature | status | evidence |
|---|---|---|
| L0–L7 ontology seeded in DB | Verified | BE:test_annotations, BE:test_migrations |
| Ontology extension (labels, tiers) with version bump | Verified | BE:test_annotations |
| L6 relationships between annotations | Verified (API) / Not implemented (UI) | BE:test_annotations |
| Integer half-open intervals, inclusive-offset conversion | Verified | BE:test_datasets, BE:test_measurements |
| Revisions, history, soft delete | Verified | BE:test_annotations, E2E-ed (history 3 entries) |
| Optimistic concurrency (409 on stale revision) | Verified | BE:test_annotations, FE:editor |
| Reviewed annotations protected (confirmation required) | Verified | BE:test_annotations, FE:editor, E2E-ed |
| Atomic batch save | Verified | BE:test_annotations, FE:editor |
| Beat grouping (`beat_id`) | Verified | BE:test_annotations |
| Multi-user / authentication | Not implemented | single local user (`actor = local-user`) |

## Real datasets (task §7)

| feature | status | evidence |
|---|---|---|
| LUDB adapter (per-lead P/QRS/T) | Verified | BE:test_datasets, EVAL (200 records) |
| QTDB adapter (global q1c boundaries, atr beats) | Verified (import) | BE:test_datasets; no quantitative QTDB evaluation |
| MIT-BIH adapter (beats, rhythm) | Verified | BE:test_datasets, EVAL (48 records) |
| Unit conversion to mV, ADC formula | Verified | BE:test_datasets |
| SHA-256 verified download from PhysioNet | Verified | used to fetch 248 evaluation records; script + API |
| Bundled redistributable samples, auto import | Verified | Docker start (10 recordings), E2E |
| NPZ upload | Verified (API) / Not implemented (UI) | BE:test_datasets upload round trip |

## Pre-annotation (task §8)

| feature | status | evidence |
|---|---|---|
| R-peak detection, Pan-Tompkins (SciPy) with stored algorithm/version/parameters | Verified | BE:test_predictions, EVAL, E2E-acc, E2E-an |
| R-peak detection, WFDB XQRS | Verified | BE:test_predictions, EVAL |
| Confidence | Partial | no calibrated confidence; a raw detection score is stored as `x_detection_score` |
| Beat segmentation with explicit boundaries | Verified | BE:test_predictions, E2E-an |
| P/QRS/T delineation | Partial (experimental) | EVAL on LUDB: QRS usable, P/T unreliable; always flagged experimental |
| Prediction layer: accept / reject / modify / accept in range | Verified | BE:test_predictions, E2E-acc step 18, E2E-an |
| Provenance on accepted predictions | Verified | E2E-acc step 18 |
| Predictions never overwrite reviewed annotations | Verified | BE:test_predictions, E2E-acc step 18 |

## Measurements (task §9)

| feature | status | evidence |
|---|---|---|
| RR, HR, PR, QRS, QT, QTc (Bazett), P duration | Verified | BE:test_measurements, E2E-ed (UI values = reference-derived values) |
| ST deviation, peak amplitudes (experimental, labelled) | Verified (labelling) / Unverified (clinical accuracy) | E2E-ed |
| N/A with reason when data is missing | Verified | BE:test_measurements, E2E-ed |
| Traceability (samples + annotation ids per value) | Verified | BE:test_measurements, measurements.csv |
| Signal-quality indicators | Verified (values) / heuristic thresholds unvalidated | BE:test_datasets, E2E-an |

## Export (task §10)

| feature | status | evidence |
|---|---|---|
| JSON (structure, metadata, relationships, provenance, ontology) | Verified | BE:test_export |
| CSV annotations + measurements | Verified | BE:test_export |
| NumPy NPZ (signal, labels, sample indices, metadata) | Verified | BE:test_export, PyTorch example |
| Segmentation masks (unannotated, uncertain, overlap, lead-specific) | Verified | BE:test_export mask codes |
| Immutable versioned snapshots with manifest and checksums | Verified | BE:test_export, E2E-acc step 19 |
| Patient-level split without leakage | Verified | BE:test_export, E2E-acc |
| Round-trip import (verify + new recording) | Verified | BE:test_export, E2E-acc steps 20–21 |
| PyTorch Dataset example | Verified (manually run) | run on a real LUDB snapshot (7 recordings, splits 3/2/2, forward/backward OK); not in CI because torch is not a backend dependency |

## UI, platform, tests (task §11–§14)

| feature | status | evidence |
|---|---|---|
| Workbench layout (top toolbar, waveform, tiers, right properties, bottom analysis), light theme | Verified | all E2E specs |
| Docker Compose on Windows 11 (`copy .env.example .env`, `docker compose up --build`) | Verified | this machine, Docker Desktop 29 |
| PostgreSQL migrations (Alembic) | Verified | BE:test_migrations on SQLite and PostgreSQL |
| 21-step acceptance workflow | Verified | E2E-acc on Docker/PostgreSQL |
| Real-dataset validation (TP/FP/FN, P/R/F1, tolerance, delineation errors) | Verified | EVAL, `docs/evaluation/results.json` |

## P2 (future, intentionally not started)

Deep-learning models, active learning, multi-expert consensus, clinical
reasoning, distributed annotation — **Not implemented**.
