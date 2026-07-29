from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import get_settings
from app.scheduler import next_daily_run, next_interval_run, planned_jobs


def test_next_hourly_run_at_minute_twenty_five() -> None:
    now = datetime(2026, 7, 1, 16, 20, tzinfo=timezone.utc)
    assert next_interval_run(now, every_hours=1, minute=25, timezone_name='UTC') == datetime(2026, 7, 1, 16, 25, tzinfo=timezone.utc)
    exact = datetime(2026, 7, 1, 16, 25, tzinfo=timezone.utc)
    assert next_interval_run(exact, every_hours=1, minute=25, timezone_name='UTC') == datetime(2026, 7, 1, 17, 25, tzinfo=timezone.utc)


def test_next_daily_run_today_or_tomorrow() -> None:
    before = datetime(2026, 7, 1, 2, 0, tzinfo=timezone.utc)
    after = datetime(2026, 7, 1, 4, 0, tzinfo=timezone.utc)
    assert next_daily_run(before, hour=3, minute=15, timezone_name='UTC') == datetime(2026, 7, 1, 3, 15, tzinfo=timezone.utc)
    assert next_daily_run(after, hour=3, minute=15, timezone_name='UTC') == datetime(2026, 7, 2, 3, 15, tzinfo=timezone.utc)


def test_planned_jobs_uses_environment(monkeypatch) -> None:
    monkeypatch.setenv('NVD_SYNC_TIMEZONE', 'UTC')
    monkeypatch.setenv('NVD_SYNC_MODIFIED_EVERY_HOURS', '1')
    monkeypatch.setenv('NVD_SYNC_MODIFIED_MINUTE', '25')
    monkeypatch.setenv('NVD_SYNC_DAILY_MIRROR_HOUR', '3')
    monkeypatch.setenv('NVD_SYNC_DAILY_MIRROR_MINUTE', '15')
    get_settings.cache_clear()
    jobs = planned_jobs(datetime(2026, 7, 1, 2, 0, tzinfo=timezone.utc))
    assert [job.name for job in jobs] == ['modified', 'daily-mirror']
    assert jobs[0].due_at_utc == datetime(2026, 7, 1, 2, 25, tzinfo=timezone.utc)
    assert jobs[1].due_at_utc == datetime(2026, 7, 1, 3, 15, tzinfo=timezone.utc)
    get_settings.cache_clear()


@dataclass
class FakeMirrorResult:
    feed: str
    status: str = 'updated'
    def as_dict(self):
        return {'feed': self.feed, 'status': self.status}


def test_modified_job_imports_modified_and_mirrors_recent(monkeypatch) -> None:
    import app.scheduler as scheduler
    calls = []
    monkeypatch.setattr(scheduler, 'run_sync', lambda **kwargs: calls.append(('sync', kwargs)) or {'mode':'modified'})
    monkeypatch.setattr(scheduler, 'mirror_feeds', lambda feeds, **kwargs: calls.append(('mirror', list(feeds))) or [FakeMirrorResult('recent')])
    result = scheduler.run_job('modified', progress=lambda _message: None)
    assert result['mode'] == 'modified-plus-recent'
    assert calls[0][0] == 'sync' and calls[0][1]['mode'] == 'modified'
    assert calls[1] == ('mirror', ['recent'])
