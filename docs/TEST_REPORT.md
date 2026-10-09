# Test report — 2026-10-09

## Executed

- `cd backend && pytest -q`: **2 passed in 1.20s**. One health test; one API roundtrip test covers NPZ upload, waveform read, point creation, update, optimistic conflict HTTP 409, list, JSON and CSV export, audit history, R detector invocation, deletion.
- PhysioNet official MIT-BIH 100.hea download: **FAILED** — external DNS/network unavailable (`NameResolutionError`). No real ECG test data are included.
- `cd frontend && npm install --ignore-scripts --no-audit --no-fund --fetch-retries=0 --fetch-timeout=8000`: **FAILED** — registry.npmjs.org DNS error EAI_AGAIN. Frontend build and Vitest not executed.
- Docker Compose: **NOT EXECUTED** — Docker CLI unavailable.
- Playwright browser E2E: **NOT EXECUTED**.
- Visual waveform/time alignment inspection: **NOT EXECUTED**.
- Real ECG detection precision/recall and reference annotation comparison: **NOT EXECUTED**.

## Scope warning

Passing two backend tests does not validate clinical accuracy, dataset provenance, waveform rendering, concurrency under load, or end-to-end usability. Synthetic sinusoid used only as test fixture; never represented as clinical ECG data.
