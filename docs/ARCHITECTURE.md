# Architecture

```
Browser (React 18 + TypeScript, Vite build)
  App.tsx ── Toolbar ─ WaveformView (canvas) ─ TierPanel (DOM) ─ PropertiesPanel ─ AnalysisPanel ─ ExportDialog
     │            ▲ shared viewport {start,end} + document state (Zustand: store/editor.ts)
     │ TanStack Query (datasets, recordings, ontology, chunks, runs, measurements)
     ▼  same-origin /api/*
nginx (frontend container, only published port) ── proxy /api/ → backend:8000/
FastAPI (backend container, internal)
  routers/  recordings · annotations · predictions · ontology · exports
  services/ annotations (validation, revisions, batches) · predictions · exporter · importer
  signal/   rpeak · delineation · measurements · quality
  datasets/ ludb · qtdb · mitdb adapters (WFDB) · download (SHA-256 verified)
  storage   float32 .npy signals (mmap) in DATA_DIR/signals
  db        SQLAlchemy 2 + Alembic  ──►  PostgreSQL 16 (db container, internal)  |  SQLite (dev/tests)
```

## Backend

* **App** (`app/main.py`): creates the FastAPI app (`root_path` from
  `ROOT_PATH`, `/api` in Docker so `/api/docs` works behind nginx), applies
  Alembic migrations at start-up (`AUTO_MIGRATE=1`), seeds the ontology and,
  with `AUTO_IMPORT_SAMPLES=1`, imports every record present in
  `DATA_DIR/physionet` (idempotent; existing recordings are skipped).
* **Configuration** (`app/config.py`): `DATA_DIR`, `DATABASE_URL` (SQLite in
  `DATA_DIR/annotations.db` when unset), `AUTO_MIGRATE`,
  `AUTO_IMPORT_SAMPLES`, `CORS_ORIGINS`. No secrets live in code; Compose
  builds `DATABASE_URL` from `.env`.
* **Signals** are not stored in the database. Import converts WFDB physical
  signals to mV float32 `[samples, leads]` and writes `signals/<id>.npy`
  (SHA-256 recorded). Reads use `np.load(mmap_mode="r")`, so a 30-minute
  MIT-BIH record is never loaded fully per request.
* **Waveform API**: `GET /recordings/{id}/chunk?bucket=b&index=i` returns
  1024 buckets of `b` samples, i.e. samples `[i·1024·b, (i+1)·1024·b)`.
  `b = 1` returns raw values; otherwise per-bucket min and max, so narrow
  extrema such as QRS complexes are never lost when zoomed out. `b` is a
  power of two chosen by the client from the current samples-per-pixel.
* **Annotations** (`services/annotations.py`): ontology validation, overlap
  policies, beat-id assignment, revision history, optimistic concurrency and
  reviewed-annotation protection. The batch endpoint applies create / update
  / delete operations in one transaction; any error rolls back the whole batch.
* **Predictions** (`services/predictions.py`) are stored in
  `prediction_runs` / `predictions` with algorithm, version and parameters,
  and become annotations only through accept / modify / accept-range.
* **Snapshots** (`services/exporter.py`) are written once, made read-only on
  disk, checksummed in a manifest and verified on demand.

## Frontend

* **State** (`store/editor.ts`, Zustand): recording, viewport, cursor,
  selection, active tier/label/lead, hidden and collapsed tiers, and the
  *document*: `server` (last saved annotations by id) and `working` (edited
  copy). Every edit is a `commit(fn)` that pushes the previous `working`
  snapshot to the undo stack; pointer drags are bracketed by
  `beginGesture`/`endGesture` so one drag is one undo step.
* **Saving** (`store/actions.ts`): `diffOps(server, working)` produces
  create/update/delete operations carrying the expected revision; if any
  touches a reviewed annotation the user must confirm, then one
  `POST /annotations/batch` is sent. On success temporary ids are remapped in
  the working copy and the undo stack; on failure nothing changes locally.
* **Rendering** (`lib/draw.ts`, `components/WaveformView.tsx`): a single
  HiDPI canvas draws the ECG paper grid (1 mm / 5 mm at 40 / 200 ms when
  zoomed in), all selected leads as stacked strips with a common mV scale,
  annotations of visible tiers (global ones as a band), predictions (dashed),
  selection, cursor and drag previews. LOD chunks are fetched through
  TanStack Query (cached, with prefetch of the neighbouring chunks).
* **Tiers** (`components/TierPanel.tsx`): DOM rows using the same viewport
  mapping (`lib/viewport.ts`); intervals have draggable start/end handles,
  points are draggable markers; rows follow the tier `order` and can be
  hidden and collapsed.
* **Keyboard** (`hooks/useKeyboard.ts`): see the README tour.

## Persistence and concurrency

* Every annotation row has `revision`; updates/deletes must send the
  `revision` they edited. A mismatch returns `409 revision_conflict` and the
  client keeps the unsaved working copy.
* Each write appends an `annotation_revisions` row with a full JSON snapshot,
  operation, actor and batch id. Deletes are soft (`deleted = true`).
* `review_status = reviewed` annotations (all imported references) reject
  changes with `409 reviewed_protected` unless `confirm_reviewed_change` is
  set; algorithm predictions are never accepted over them.

## Docker topology

* `db` (postgres:16-alpine, volume `pgdata`), `backend` (python:3.12-slim,
  non-root uid 1000, volume `appdata:/data`, bundled `./data/physionet`
  mounted), `frontend` (multi-stage node:22 build → nginx:1.27). Health checks
  gate start-up order. Only `frontend` publishes a port (`FRONTEND_PORT`,
  default 5173).
* Profile `test`: `db-test` (tmpfs, throw-away credentials) and
  `backend-tests` running pytest against PostgreSQL.
