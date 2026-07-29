from __future__ import annotations

import sqlite3
import sys

from sqlalchemy import inspect


def _reload_db_modules() -> object:
    for module_name in ('app.models', 'app.db', 'app.config'):
        sys.modules.pop(module_name, None)
    import app.config as config_module
    config_module.get_settings.cache_clear()
    import app.db as db_module
    import app.models  # noqa: F401
    return db_module


def test_create_tables_backfills_missing_indexes_for_existing_table(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / 'index-backfill.sqlite3'
    conn = sqlite3.connect(db_path)
    conn.execute('create table nvd_cves (cve_id varchar(32) primary key, year integer, published datetime, last_modified datetime, source_feed varchar(64), raw_json text not null, imported_at datetime not null)')
    conn.commit(); conn.close()
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{db_path}')
    db_module = _reload_db_modules()
    db_module.create_tables()
    index_names = {index['name'] for index in inspect(db_module.engine).get_indexes('nvd_cves')}
    assert {'ix_nvd_cves_year','ix_nvd_cves_published','ix_nvd_cves_last_modified','ix_nvd_cves_source_feed','ix_nvd_cves_pub_lastmod'} <= index_names
