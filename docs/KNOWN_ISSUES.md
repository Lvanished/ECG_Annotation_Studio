# Known issues and limitations

## Algorithms

* **Delineation is experimental.** On held-out LUDB records the T offset
  error has SD ≈ 98 ms and only ≈ 48–58 % of P boundaries are within CSE
  tolerance. Use it only as a starting point for manual correction. The
  calibration split was not perfectly untouched (see `TEST_REPORT.md`).
* **Pan-Tompkins false positives on noisy records.** Version 1.1.0 added
  search-back and threshold re-learning, which raised recall but also false
  positives (MIT-BIH 207: 398, 108: 329, 114: 207, 232: 136). It was tuned
  while looking at MIT-BIH, so the MIT-BIH figures are not an independent
  test.
* **WFDB XQRS on 10-second records** misses beats (LUDB recall 0.912)
  because its learning phase needs more signal. Prefer Pan-Tompkins on short
  records.
* **No calibrated confidence.** Predictions carry a raw detector score
  (`x_detection_score`), not a probability.
* **Evaluation protocol deviations**: MIT-BIH scored from sample 0 (EC57
  skips the first 5 minutes); LUDB R-peak scoring excludes record 104 (no
  lead-II QRS intervals) and the unannotated edge beats. QTDB was not
  evaluated quantitatively.
* **Signal-quality flags** use heuristic thresholds that have not been
  validated; the numeric indicators themselves are exact.
* **ST deviation and amplitude measurements** are marked experimental
  (baseline = median of the PR segment or of a fixed pre-QRS window).

## Data handling

* WFDB invalid samples (NaN) are zero-filled on import; there is no
  automatic `missing_data` annotation for them.
* QTDB `.q1c` boundaries are imported as global (both-lead) annotations
  because the annotator used both leads; there is no per-lead version.
* Only the first QTDB annotator (`q1c`) is imported; `q2c` and the
  automatic `.pu*` files are not.
* Patient identity: LUDB and QTDB have one record per patient (used as the
  group); MIT-BIH 201/202 are mapped to the same subject. Uploaded
  recordings have no patient id, so each upload is its own group.
* Snapshot export loads each recording's full signal into memory to write
  the NPZ; exporting many 30-minute records at once is slow (not
  benchmarked).

## Application

* **Single user, no authentication.** Every edit is attributed to
  `local-user`. Do not expose the stack to a network. Concurrency between
  browser tabs is handled by revision checks (409), not by live merging.
* **No UI for L6 relationships or NPZ upload** — both are API only
  (`POST /recordings/{id}/relationships`, `POST /recordings/upload`).
* **Prediction runs accumulate.** Every detection run is stored; discard old
  runs from the run list (or `DELETE /prediction-runs/{id}`).
* **E2E leftovers.** The acceptance test imports its snapshot as a new
  recording each run (`ludb/3 [import e2e_ludb3-vN …]`) and leaves it and the
  export behind; the other specs clean up after themselves. Use a throw-away
  database (`docker compose down -v`) to reset.
* Snapshot versions are immutable, so names are auto-suffixed (`-v2`, …).
  Deleting snapshots is not exposed.
* Pan gestures (middle-button drag, Shift+wheel), drag-selection + `z`, and
  the panel splitters have no dedicated automated test.
* Chromium is the only browser tested.
* `starlette.testclient` prints a deprecation warning about `httpx` during
  the backend tests (no functional effect).

## Environment notes (development machine)

* Port 8000 was occupied by an unrelated local service, so the dev backend
  was run on 8010 (`API_PROXY_TARGET=http://127.0.0.1:8010`). Docker Compose
  does not publish the backend, so it is not affected.
* Docker Hub pulls occasionally timed out; re-running the command succeeded.
