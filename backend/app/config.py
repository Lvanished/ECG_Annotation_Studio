"""Environment-based configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_DATA = Path(__file__).resolve().parents[2] / "data"


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", str(_DEFAULT_DATA))).resolve())
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))
    auto_migrate: bool = field(default_factory=lambda: _bool("AUTO_MIGRATE", True))
    auto_import_samples: bool = field(default_factory=lambda: _bool("AUTO_IMPORT_SAMPLES", False))
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()
        )
    )
    max_upload_bytes: int = 150_000_000

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.data_dir / 'annotations.db').as_posix()}"

    @property
    def physionet_dir(self) -> Path:
        return self.data_dir / "physionet"

    @property
    def signals_dir(self) -> Path:
        return self.data_dir / "signals"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"


def get_settings() -> Settings:
    return Settings()
