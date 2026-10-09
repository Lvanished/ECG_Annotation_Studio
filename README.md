# ECG Annotation Studio — research prototype 0.1.0

Praat-inspired ECG time annotation. **Prototype, not a medical diagnostic device.** This is a limited functional vertical slice, not the complete requested production system.

## Start on Windows 11 (Docker Desktop)

1. Install Docker Desktop, start Docker Engine.
2. Extract ZIP, open a terminal in `ECG_Annotation_Studio`.
3. Run `copy .env.example .env` and edit the local password if desired.
4. Run `docker compose up --build`.
5. Open http://localhost:5173 ; API http://localhost:8000 ; Swagger http://localhost:8000/docs . PostgreSQL runs in Docker and is not exposed to the host.

## Load a real ECG record

Network access was unavailable in the build environment, so **no PhysioNet ECG has been downloaded or validated here**. When connected to the internet:

```bash
python -m pip install wfdb numpy
python scripts/download_datasets.py
python scripts/import_wfdb.py data/samples/100
python scripts/verify_datasets.py data/samples/100.npz
```

Then use **Import NPZ** in the app and select `data/samples/100.npz`. Data are real only after you perform this download. MIT-BIH record 100 is a 2-lead recording, not a 12-lead sample. Use the original `.atr` for reference annotation comparison (reference-annotation import is not yet implemented).

## Manual local development

Run PostgreSQL through `docker compose up -d db` (recommended). Set `DATABASE_URL=postgresql+psycopg://ecg:<password>@localhost:5432/ecg` only if you expose port 5432 in compose; otherwise use the default SQLite fallback for local development:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

In a second terminal: `cd frontend`, `npm install`, `npm run dev`. The Vite proxy defaults to `http://localhost:8000` outside Docker and uses `http://backend:8000` inside Docker.

## Tests

`cd backend && pytest -q` and `cd frontend && npm test && npm run build`. See `docs/TEST_REPORT.md` for actual results.

## Known limitations

- No reference annotation importer, no dataset-specific LUDB/QTDB adapters, no 12-lead layout, no signal-quality assessment.
- No drag-to-edit boundary, multi-lead synchronized view, waveform chunk caching, undo/redo, keyboard shortcuts, batch annotation transaction, annotation schema configuration or patient-level split.
- No Alembic migrations (SQLAlchemy creates initial tables); no immutable dataset versions, segmentation masks or PyTorch dataset exporter.
- AI candidate layer is session-local; accepted points are saved as manual annotations. The R-peak detector is a research baseline, **not validated** on MIT-BIH in this environment.
- Display downsampling is simple stride decimation; can hide narrow extrema when zoomed out.
- Edits on blur use an optimistic revision, but rapid successive edits may conflict. No authentication or multi-user permissions.
- The waveform viewer assumes uploaded NPZ signals are already calibrated in millivolts.

See `docs/CURSOR_HANDOFF.md` for next steps.
