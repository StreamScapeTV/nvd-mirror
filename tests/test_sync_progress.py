from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import app.sync as sync_module


class FakeResult:
    def scalar_one_or_none(self):
        return SimpleNamespace(feed='modified')


class FakeSession:
    def execute(self, statement):
        del statement
        return FakeResult()


@contextmanager
def fake_session_scope():
    yield FakeSession()


def test_run_sync_reports_feed_progress(monkeypatch, capsys) -> None:
    def fake_import(feed, db, progress=None):
        del db
        if progress:
            progress(f'inner progress for {feed}')
        return {'feed': feed, 'recordsImported': 123, 'meta': {}, 'validation': {}}

    monkeypatch.setattr(sync_module, 'create_tables', lambda: None)
    monkeypatch.setattr(sync_module, 'session_scope', fake_session_scope)
    monkeypatch.setattr(sync_module, 'has_existing_cves', lambda db: True)
    monkeypatch.setattr(sync_module, 'import_feed', fake_import)
    monkeypatch.setattr(sync_module, 'refresh_nvd_stats_snapshot', lambda db, progress=None: {})

    result = sync_module.run_sync(mode='all', from_year=2024, to_year=2025)
    output = capsys.readouterr().out.lower()
    assert result['feeds'] == ['2024', '2025', 'modified']
    assert 'planned feeds (3): 2024, 2025, modified' in output
    assert 'starting feed 1/3: 2024' in output
    assert 'inner progress for 2024' in output
    assert 'completed feed 3/3: modified' in output
