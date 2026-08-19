"""Database engine and session configuration."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://bibmgr:bibmgr@127.0.0.1:5432/bibmgr"
)


def database_url() -> str:
    """Return the configured synchronous SQLAlchemy database URL."""

    configured = (
        os.environ.get("BIBMGR_DATABASE_URL")
        or _file_secret("BIBMGR_DATABASE_URL_FILE")
        or os.environ.get("DATABASE_URL")
        or DEFAULT_DATABASE_URL
    )
    if configured.startswith("postgres://"):
        return configured.replace("postgres://", "postgresql+psycopg://", 1)
    if configured.startswith("postgresql://"):
        return configured.replace(
            "postgresql://", "postgresql+psycopg://", 1
        )
    return configured


def _file_secret(environment_name: str) -> str | None:
    path = os.environ.get(environment_name)
    if not path:
        return None
    value = Path(path).read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"{environment_name} points to an empty file.")
    return value


def create_database_engine(url: str | None = None) -> Engine:
    selected_url = url or database_url()
    options: dict[str, object] = {}
    if selected_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    else:
        options["pool_pre_ping"] = True
    return create_engine(selected_url, **options)


engine = create_database_engine()
SessionFactory = sessionmaker(
    bind=engine,
    class_=Session,
    expire_on_commit=False,
)
