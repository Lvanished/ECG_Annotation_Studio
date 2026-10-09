"""Alembic migrations: upgrade/downgrade on a fresh database and no drift vs ORM models."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

BACKEND = Path(__file__).resolve().parents[1]


def _cfg(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.mark.skipif(bool(os.getenv("TEST_DATABASE_URL")), reason="uses its own SQLite file")
def test_upgrade_downgrade_and_no_drift():
    from app.db import Base
    from app import models  # noqa: F401

    url = f"sqlite:///{Path(tempfile.mkdtemp()) / 'm.db'}"
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
