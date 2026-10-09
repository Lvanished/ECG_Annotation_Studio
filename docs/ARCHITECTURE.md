# Architecture

React/Vite Canvas UI -> FastAPI REST -> SQLAlchemy -> PostgreSQL; raw signal arrays stored as compressed NPZ files. The frontend requests a window by integer sample indices; the backend returns decimated samples and calibrated millivolt values. Annotation intervals are half-open, point annotations use null end. Audit snapshots track mutations and revisions prevent stale writes. No background worker or cloud storage is included.
