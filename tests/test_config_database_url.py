from __future__ import annotations

from app.config import normalize_database_url


def test_normalize_cnpg_postgres_url_to_psycopg_driver() -> None:
    assert normalize_database_url('postgresql://user:pass@db:5432/nvdcache-db') == (
        'postgresql+psycopg://user:pass@db:5432/nvdcache-db'
    )


def test_keep_existing_psycopg_database_url_unchanged() -> None:
    assert normalize_database_url('postgresql+psycopg://user:pass@db:5432/nvd') == (
        'postgresql+psycopg://user:pass@db:5432/nvd'
    )
