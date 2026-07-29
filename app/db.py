from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

connect_args = {}
if settings.database_url.startswith('sqlite'):
    connect_args = {'check_same_thread': False}
    # Ensure /data exists for the default SQLite path in the container.
    if settings.database_url.startswith('sqlite:////'):
        db_path = settings.database_url.replace('sqlite:///', '', 1)
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _create_missing_indexes() -> None:
    # create_all() will not backfill indexes onto existing tables, so ensure
    # declared indexes are present after startup on long-lived databases.
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            index.create(bind=engine, checkfirst=True)


def create_tables() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _create_missing_indexes()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
