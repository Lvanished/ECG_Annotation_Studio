"""Test fixtures.

Tests run against **real PhysioNet records** bundled in ``data/physionet``
(copied into a temporary DATA_DIR).  Set ``TEST_DATABASE_URL`` to run the
suite against PostgreSQL instead of the default temporary SQLite database.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
PHYSIONET = REPO / "data" / "physionet"
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="ecg_test_"))
os.environ["DATA_DIR"] = str(_TMP)
os.environ["AUTO_IMPORT_SAMPLES"] = "0"
if os.getenv("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
else:
    os.environ.pop("DATABASE_URL", None)

NEEDED = {"ludb": ["data/1", "data/2"], "qtdb": ["sel100"], "mitdb": ["100"]}


def _copy_samples() -> None:
    for ds, bases in NEEDED.items():
        src_root = PHYSIONET / ds
        for base in bases:
            for f in src_root.glob(base + ".*"):
                dst = _TMP / "physionet" / ds / f.relative_to(src_root)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)


def _reset_postgres() -> None:
    from sqlalchemy import create_engine, text

    eng = create_engine(os.environ["DATABASE_URL"])
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    eng.dispose()


@pytest.fixture(scope="session")
def client():
    missing = [ds for ds, bases in NEEDED.items() for b in bases if not (PHYSIONET / ds / f"{b}.hea").exists()]
    if missing:
        pytest.fail(f"Real PhysioNet samples missing ({missing}); run: python scripts/download_datasets.py --preset bundled")
    _copy_samples()
    if os.getenv("TEST_DATABASE_URL"):
        _reset_postgres()
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
    from app.db import reset_engine

    reset_engine()


@pytest.fixture(scope="session")
def imported(client):
    """Import the real sample records once; returns {(dataset, record): recording dict}."""
    out = {}
    for ds, bases in NEEDED.items():
        names = [b.split("/")[-1] for b in bases]
        r = client.post(f"/datasets/{ds}/import", json={"records": names})
        assert r.status_code == 200, r.text
        rep = r.json()[ds]
        assert not rep["failed"], rep
    for rec in client.get("/recordings").json():
        out[(rec["dataset_id"], rec["name"])] = rec
    return out


@pytest.fixture()
def ludb1(imported):
    return imported[("ludb", "1")]


@pytest.fixture()
def mitdb100(imported):
    return imported[("mitdb", "100")]
