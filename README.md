# ECG Annotation Studio — research prototype 1.0.0

A Praat-inspired workbench for sample-exact, multi-tier ECG annotation, built to
produce training data for medical-AI research (segmentation, delineation and
beat/rhythm classification).

> **Research prototype. Not a medical device and not for clinical use.**
> Algorithmic pre-annotations are suggestions that a human reviews; the
> wave delineator is explicitly experimental (see `docs/TEST_REPORT.md`).

What you get:

* Shared-viewport waveform + tier editor (P, QRS, T, ST, PR, U, Rhythm, Beat,
  Fiducial Points, Morphology, Signal Quality, Interpretation, custom tiers),
  mouse and keyboard editing, undo/redo, explicit save with conflict detection.
* Ontology L0–L7 stored in the database and extensible at runtime.
* Integer-sample, half-open `[start, end)` annotation model with revisions,
  history, optimistic concurrency and protection of reviewed annotations.
* Real PhysioNet data: LUDB, QTDB and MIT-BIH adapters; 10 records are bundled
  and imported automatically (ODC-By 1.0, see `docs/THIRD_PARTY_AND_DATA.md`).
* Pre-annotation (Pan-Tompkins, WFDB XQRS, beat segmentation, experimental
  delineation) kept as reviewable predictions, never mixed into annotations.
* Traceable measurements (RR, HR, PR, QRS, QT, QTc; experimental amplitudes)
  that report N/A with a reason instead of guessing.
* Immutable, checksummed dataset snapshots (JSON, CSV, NPZ with segmentation
  masks, patient-level splits) with verified round-trip import, plus a
  PyTorch `Dataset` example.

Feature-by-feature status: `docs/FEATURE_MATRIX.md`. Test evidence:
`docs/TEST_REPORT.md`. Limitations: `docs/KNOWN_ISSUES.md`.

---

## Start on Windows 11 (Docker Desktop)

Requirements: Docker Desktop with the WSL 2 engine running. No local Python,
Node or PostgreSQL is needed — PostgreSQL runs inside Docker, is **not
published to the host**, and therefore never interferes with a local
PostgreSQL service.

```bat
cd ECG_Annotation_Studio
copy .env.example .env
docker compose up --build
```

Then open **http://localhost:5173**.

* Edit `.env` before the first start to choose your own local database
  password (`POSTGRES_PASSWORD`). Compose refuses to start without it.
* If port 5173 is taken, set `FRONTEND_PORT=8080` (for example) in `.env`.
* Only the frontend port is published. The API is reachable through the same
  origin: `http://localhost:5173/api/health`, interactive docs at
  `http://localhost:5173/api/docs`.
* The first start applies the Alembic migrations and imports the bundled
  PhysioNet records (`AUTO_IMPORT_SAMPLES=1`); this takes a few seconds.
* Data persists in the Docker volumes `pgdata` and `appdata`.
  `docker compose down` keeps them; `docker compose down -v` deletes **this
  project's** volumes only (project name `ecg-annotation-studio`).

A control-by-control guide (Chinese) is in [`USER_MANUAL.md`](USER_MANUAL.md).

## Using the studio (quick tour)

1. Pick a dataset and recording in the header (on an empty database press
   *Register local PhysioNet records*).
2. Zoom with the mouse wheel (anchored at the pointer); pan with a
   middle-button drag or `Shift`+wheel; `f` fits the whole record, `+`/`-`
   zoom, `z` zooms to the selection (a left-drag with the select tool `v`).
   You can also type an exact sample range. Long records are drawn as min/max
   envelopes and switch to raw samples when zoomed in.
3. Choose the active tier (number keys `1`–`9`) and label in the toolbar and
   switch to the annotate tool (`a`). Drag on the waveform to create an
   interval; click (waveform) or double-click (tier row) to create a point.
   `Enter` creates an annotation from the current selection or cursor.
4. Drag boundaries or points (whole samples, one undo step per drag), nudge
   with `Alt+←/→` (`Shift` = 10 samples), delete with `Del`, undo/redo with
   `Ctrl+Z` / `Ctrl+Shift+Z` / `Ctrl+Y`, step between beats with `[` / `]`.
5. Edit label, lead, boundaries, morphology, review status and notes in the
   right panel; the history of every saved annotation is listed there.
6. `Ctrl+S` saves all edits as one atomic batch. Changing a *reviewed*
   annotation requires an explicit confirmation.
7. Run R-peak detection / delineation from the toolbar; predictions appear
   dashed in their tiers and are accepted, modified or rejected individually
   (or accepted for a range) in the right panel.
8. *Export / import* creates immutable snapshots and verifies round trips.

## Development without Docker

Python 3.11+ (tested 3.13) and Node 20+ (tested 20.20). Without
`DATABASE_URL` the backend uses SQLite in `data/annotations.db`.

```powershell
# backend (any free port; 8000 is the default)
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
$env:AUTO_IMPORT_SAMPLES = "1"
.\.venv\Scripts\python -m uvicorn app.main:app --port 8010

# frontend (second terminal): proxies /api to the backend
cd frontend
npm ci
$env:API_PROXY_TARGET = "http://127.0.0.1:8010"
npm run dev
```

## Tests

```powershell
# backend unit/integration tests on real PhysioNet records (SQLite)
cd backend; .\.venv\Scripts\python -m pytest -q

# the same suite against PostgreSQL 16 in Docker (isolated tmpfs database)
docker compose --profile test run --rm --build backend-tests

# frontend unit/component tests, type check, production build
cd frontend; npm test; npm run typecheck; npm run build

# end-to-end acceptance tests against a running stack (Docker or dev)
cd frontend; npx playwright install chromium
$env:E2E_BASE_URL = "http://localhost:5173"; npx playwright test
```

## Real-data validation

```powershell
# downloads all 48 MIT-BIH and 200 LUDB records (~110 MB, SHA-256 verified)
backend\.venv\Scripts\python scripts\download_datasets.py --preset evaluation --out data/physionet_eval
backend\.venv\Scripts\python scripts\evaluate.py --root data/physionet_eval --out docs/evaluation
```

Results are written to `docs/evaluation/results.json` and summarised in
`docs/TEST_REPORT.md`.

## Documentation

| Document | Content |
|---|---|
| `USER_MANUAL.md` | user guide for every on-screen control |
| `docs/ARCHITECTURE.md` | components, data flow, rendering, persistence |
| `docs/ANNOTATION_SCHEMA.md` | data model, ontology L0–L7, tiers, revisions, review |
| `docs/DATA_FORMAT.md` | signal storage, dataset adapters, upload, snapshot format, masks |
| `docs/FEATURE_MATRIX.md` | every feature with its verification status |
| `docs/TEST_REPORT.md` | test runs and real-dataset metrics |
| `docs/KNOWN_ISSUES.md` | limitations and open problems |
| `docs/IMPLEMENTATION_PLAN.md` | plan and phase status |
| `docs/DEVELOPMENT_LOG.md` | chronological development and debugging log |
| `docs/CURSOR_HANDOFF.md` | where to continue, conventions, pitfalls |
| `docs/THIRD_PARTY_AND_DATA.md` | licences and dataset citations |

## Licence

Source code: MIT (`LICENSE`). Bundled PhysioNet records: Open Data Commons
Attribution License v1.0 — cite the datasets as listed in
`docs/THIRD_PARTY_AND_DATA.md`.
