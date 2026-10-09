# Cursor handoff

Read `README.md`, then `docs/ARCHITECTURE.md`, `docs/ANNOTATION_SCHEMA.md`
and `docs/KNOWN_ISSUES.md`.

## Where things live

| concern | files |
|---|---|
| API entry, start-up (migrate, seed, auto-import) | `backend/app/main.py`, `config.py`, `db.py` |
| Models / migration | `backend/app/models.py`, `backend/alembic/versions/0001_initial_schema.py` |
| Ontology seed + validation | `backend/app/ontology.py` |
| Annotation rules (overlap, revisions, review, batch) | `backend/app/services/annotations.py` |
| Dataset adapters | `backend/app/datasets/{ludb,qtdb,mitdb}.py`, `base.py`, `download.py` |
| Algorithms | `backend/app/signal/{rpeak,delineation,measurements,quality}.py` |
| Predictions | `backend/app/services/predictions.py`, `routers/predictions.py` |
| Export / import | `backend/app/services/exporter.py` |
| Editor state, undo, save | `frontend/src/store/editor.ts`, `store/actions.ts` |
| Viewport / LOD / drawing | `frontend/src/lib/{viewport,lod,draw}.ts` |
| UI components | `frontend/src/components/*`, `App.tsx`, `hooks/useKeyboard.ts` |
| Tests | `backend/tests`, `frontend/src/**/*.test.ts(x)`, `frontend/e2e/*.spec.ts` |
| Evaluation | `scripts/evaluate.py`, `scripts/calibrate_delineation.py`, `docs/evaluation/results.json` |

## Conventions that must not be broken

* Positions are integer samples; intervals `[start, end)`. Convert inclusive
  dataset offsets with `+1` at import, nowhere else.
* Signals are mV float32 `[n, leads]` on disk; the DB holds metadata only.
* Reference annotations are `source=reference, review_status=reviewed`;
  never modify them silently, and never let predictions overwrite them.
* Predictions stay in `predictions` until a human accepts them.
* Every ontology change bumps the version (`bump_version`).
* Snapshots are immutable: never write into an existing export directory.
* Schema changes need a new Alembic revision; `test_migrations` checks that
  models and migrations do not drift.
* UI controls must have working handlers and `data-testid`s; E2E tests use
  them.

## Adding things

* **Tier or label**: add to `DEFAULT_TIERS` / `DEFAULT_LABELS` (existing
  databases get them at the next start; seeding is idempotent) or use
  `POST /tiers` / `POST /ontology/labels` at runtime.
* **Dataset**: subclass `DatasetAdapter` in `backend/app/datasets/`,
  register it in `datasets/__init__.py`, and preserve the dataset's
  annotation semantics (lead-specific vs global, inclusive offsets, original
  symbols in `attributes.original_symbol`).
* **Algorithm**: return absolute sample indices, store a `PredictionRun`
  with name, version and parameters, mark it `experimental` unless it has
  been evaluated, and add it to `scripts/evaluate.py`.

## Running everything

See README *Tests*. The E2E specs expect the bundled records (ludb 2, 3, 4
and mitdb 100) to be imported. They clean up after themselves, except that
the acceptance spec leaves one imported recording and one export per run.
On Windows, use `$env:E2E_BASE_URL = "http://localhost:5173"`.

## Pitfalls seen during development

* jsdom lacks `PointerEvent`; `src/test/setup.ts` polyfills it.
* LUDB edge beats are unannotated, and the last annotated beat of a record
  may lack a T wave; tests use edge beats for manual annotations.
* `motion_artifact` and other ontology labels stay bound to their tiers even
  on free-label tiers.
* The `backend-tests` image copies `tests/` at build time; use
  `docker compose --profile test run --rm --build backend-tests` so edited
  tests are included.
