# Implementation plan

Plan drawn up after auditing v0.1.0, executed in this order (P0 before P1;
P2 deliberately not started). The status column reflects the final state.
Details are in `FEATURE_MATRIX.md`.

| phase | scope | status |
|---|---|---|
| 1. Backend foundation | modular FastAPI package, SQLAlchemy 2 models, Alembic migration, config via env, PostgreSQL + SQLite | Done, verified (migration test on both engines) |
| 2. Data model | integer half-open samples, revisions/history, optimistic concurrency, reviewed protection, atomic batches, overlap policies, beat ids, relationships | Done, verified |
| 3. Ontology | L0–L7 seed in DB, validation, attribute schemas, runtime extension + versioning, custom tiers | Done, verified |
| 4. Real data | WFDB adapters LUDB / QTDB / MIT-BIH, mV conversion, SHA-256 download, bundled samples, auto-import, NPZ upload | Done, verified |
| 5. Waveform service | mmap signals, LOD min/max chunks, raw samples | Done, verified |
| 6. Editor frontend | canvas waveform + DOM tiers on one viewport, editing, drag, undo/redo, shortcuts, save/conflicts, panels | Done, verified (unit + E2E) |
| 7. Pre-annotation | Pan-Tompkins, XQRS, beat segmentation, experimental delineation, prediction review | Done; delineation remains experimental |
| 8. Measurements | RR/HR/PR/QRS/QT/QTc/P, experimental ST and amplitudes, quality indicators, N/A reasons, traceability | Done, verified |
| 9. Export | snapshots (JSON/CSV/NPZ/masks), manifest, immutability, patient splits, round-trip import, PyTorch example | Done, verified |
| 10. Tests | pytest (real data), Vitest, Playwright 21-step acceptance + editor + analysis specs | Done, all passing |
| 11. Real-data validation | MIT-BIH 48, LUDB 200: R-peak P/R/F1, delineation errors, held-out split | Done (see TEST_REPORT) |
| 12. Docker / Windows | Compose with internal DB/backend, health checks, test profile | Done, verified on Windows 11 |
| 13. Documentation + release ZIP | all docs with measured results | Done |

## Next steps (not started)

1. Better delineation: a trained segmentation model (e.g. U-Net on the
   exported LUDB masks, patient-split) behind the same prediction interface,
   evaluated on the held-out split.
2. UI for L6 relationships and NPZ upload.
3. Authentication and multi-annotator workflows (per-annotator layers,
   consensus, inter-rater agreement).
4. Quantitative QTDB evaluation (q1c vs. delineator, QT error).
5. Snapshot export streaming for large collections; performance benchmarks.
6. Cross-browser E2E (Firefox, WebKit) and CI pipeline.
