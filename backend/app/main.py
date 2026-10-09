"""ECG Annotation Studio API."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from . import __version__
from .config import get_settings
from .db import get_engine, session_scope
from .ontology import get_version, seed_ontology
from .routers import annotations, exports, ontology, predictions, recordings

log = logging.getLogger("ecg")
BACKEND_DIR = Path(__file__).resolve().parents[1]


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().db_url.replace("%", "%%"))
    command.upgrade(cfg, "head")


def init_app_state() -> None:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if settings.auto_migrate:
        run_migrations()
    with session_scope() as s:
        seed_ontology(s)
    if settings.auto_import_samples:
        from .services.importer import import_available

        with session_scope() as s:
            report = import_available(s)
            log.info("Sample import: %s", report)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_app_state()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="ECG Annotation Studio API", version=__version__, lifespan=lifespan,
                  root_path=os.getenv("ROOT_PATH", ""),
                  description="Praat-inspired, sample-accurate ECG annotation. Research prototype - not a medical device.")
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"],
                       allow_headers=["*"])

    @app.get("/health", tags=["system"])
    def health():
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
        with session_scope() as s:
            ov = get_version(s)
        return {"status": "ok", "version": __version__, "database": get_engine().dialect.name, "ontology_version": ov}

    for r in (recordings.router, annotations.router, predictions.router, ontology.router, exports.router):
        app.include_router(r)
    return app


app = create_app()
