"""Alembic migrations: upgrade/downgrade on a fresh database and no drift vs ORM models.

Runs on a fresh SQLite file and, when TEST_DATABASE_URL points to PostgreSQL,
additionally in an isolated PostgreSQL schema.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

BACKEND = Path(__file__).resolve().parents[1]
PG_SCHEMA = "migration_test"


def _cfg(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def _targets() -> list:
    out = [pytest.param("sqlite", id="sqlite")]
    url = os.getenv("TEST_DATABASE_URL", "")
    if url.startswith("postgresql"):
        out.append(pytest.param("postgresql", id="postgresql"))
    return out


@pytest.mark.parametrize("backend", _targets())
def test_upgrade_downgrade_and_no_drift(backend):
    from app.db import Base
    from app import models  # noqa: F401

    if backend == "sqlite":
        url = f"sqlite:///{Path(tempfile.mkdtemp()) / 'm.db'}"
    else:
        base = os.environ["TEST_DATABASE_URL"]
        admin = create_engine(base)
        with admin.begin() as c:
            c.execute(text(f"DROP SCHEMA IF EXISTS {PG_SCHEMA} CASCADE; CREATE SCHEMA {PG_SCHEMA}"))
        admin.dispose()
        url = f"{base}{'&' if '?' in base else '?'}options=-csearch_path%3D{PG_SCHEMA}"
    try:
        command.upgrade(_cfg(url), "head")
        eng = create_engine(url)
        tables = set(inspect(eng).get_table_names())
        assert {"recordings", "annotations", "annotation_revisions", "predictions", "dataset_snapshots",
                "tiers", "ontology_labels", "annotation_relationships"} <= tables
        with eng.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        assert diff == [], diff
        command.downgrade(_cfg(url), "base")
        assert set(inspect(eng).get_table_names()) <= {"alembic_version"}
        eng.dispose()
    finally:
        if backend == "postgresql":
            admin = create_engine(os.environ["TEST_DATABASE_URL"])
            with admin.begin() as c:
                c.execute(text(f"DROP SCHEMA IF EXISTS {PG_SCHEMA} CASCADE"))
            admin.dispose()
