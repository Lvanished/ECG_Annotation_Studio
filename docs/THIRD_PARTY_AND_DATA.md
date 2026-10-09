# Third-party software and data

## Source code

The project source is MIT licensed (`LICENSE`). Runtime dependencies keep
their own licences (see each package): FastAPI, Starlette, Uvicorn,
SQLAlchemy, Alembic, Pydantic, NumPy, SciPy, WFDB-Python (MIT), psycopg
(LGPL-3.0, used unmodified as a library), React, Zustand, TanStack Query,
Tailwind CSS, Vite, TypeScript, Vitest, Playwright, nginx, PostgreSQL.
No dependency source code is redistributed in this package; Docker and the
package managers fetch them at build time.

## ECG data

All three databases are published on PhysioNet under the **Open Data
Commons Attribution License v1.0 (ODC-By 1.0)**, which permits
redistribution with attribution. The records bundled in `data/physionet`
are unmodified copies of the PhysioNet files (SHA-256 checksums in each
`SHA256SUMS.txt`; download provenance in `download_manifest.json`).

| dataset | bundled records | source |
|---|---|---|
| LUDB 1.0.1 | 1, 2, 3, 4, 5, 6 (+ `ludb.csv`, `LICENSE.txt`) | https://physionet.org/content/ludb/1.0.1/ |
| QT Database 1.0.0 | sel100, sel103 | https://physionet.org/content/qtdb/1.0.0/ |
| MIT-BIH Arrhythmia Database 1.0.0 | 100, 105 | https://physionet.org/content/mitdb/1.0.0/ |

The full evaluation sets (LUDB 200 records, MIT-BIH 48 records) are **not**
included; `scripts/download_datasets.py --preset evaluation` downloads them.

### Required citations

* **LUDB**: Kalyakulina A, Yusipov I, Moskalenko V, Nikolskiy A, Kosonogov K,
  Zolotykh N, Ivanchenko M. Lobachevsky University Electrocardiography
  Database (version 1.0.1). PhysioNet (2021).
  https://doi.org/10.13026/eegm-h675 — and the original article:
  Kalyakulina AI et al. LUDB: a new open-access validation tool for
  electrocardiogram delineation algorithms. IEEE Access 8:186181–186190
  (2020).
* **QTDB**: Laguna P, Mark RG, Goldberger AL, Moody GB. A Database for
  Evaluation of Algorithms for Measurement of QT and Other Waveform Intervals
  in the ECG. Computers in Cardiology 24:673–676 (1997).
  https://doi.org/10.13026/C24K59
* **MIT-BIH**: Moody GB, Mark RG. The impact of the MIT-BIH Arrhythmia
  Database. IEEE Eng in Med and Biol 20(3):45–50 (2001).
  https://doi.org/10.13026/C2F305
* **PhysioNet** (for all three): Goldberger AL, Amaral LAN, Glass L,
  Hausdorff JM, Ivanov PCh, Mark RG, Mietus JE, Moody GB, Peng C-K, Stanley
  HE. PhysioBank, PhysioToolkit, and PhysioNet: Components of a New Research
  Resource for Complex Physiologic Signals. Circulation 101(23):e215–e220
  (2000).

The same citation strings are returned by `GET /datasets` and shown in the
recording information panel.

## Algorithms

* Pan-Tompkins QRS detection: Pan J, Tompkins WJ. A real-time QRS detection
  algorithm. IEEE Trans Biomed Eng 32(3):230–236 (1985). Implemented from the
  paper in `backend/app/signal/rpeak.py` (SciPy filters).
* XQRS: from WFDB-Python (`wfdb.processing.XQRS`, MIT licence).
* CSE tolerances used in the evaluation: CSE Working Party, Recommendations
  for measurement standards in quantitative electrocardiography. Eur Heart J
  6:815–825 (1985).
