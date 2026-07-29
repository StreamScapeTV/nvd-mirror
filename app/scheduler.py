from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.feed_mirror import iter_year_feeds, mirror_feeds
from app.sync import run_sync

ProgressCallback = Callable[[str], None]
SchedulerJobName = Literal['modified', 'daily-mirror']


@dataclass(frozen=True)
class ScheduledJob:
    name: SchedulerJobName
    due_at_utc: datetime

    def as_dict(self) -> dict[str, str]:
        return {'name': self.name, 'dueAtUtc': self.due_at_utc.isoformat()}


def _emit(message: str) -> None:
    print(f'[scheduler] {datetime.now(timezone.utc).isoformat(timespec="seconds")}Z {message}', flush=True)


def load_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f'Invalid NVD_SYNC_TIMEZONE: {name!r}') from exc


def next_interval_run(now_utc: datetime, *, every_hours: int, minute: int, timezone_name: str) -> datetime:
    if every_hours < 1 or every_hours > 24 or 24 % every_hours != 0:
        raise ValueError('every_hours must divide 24 cleanly and be between 1 and 24')
    if minute < 0 or minute > 59:
        raise ValueError('minute must be between 0 and 59')
    tz = load_timezone(timezone_name)
    local_now = now_utc.astimezone(tz)
    base = local_now.replace(second=0, microsecond=0)
    for offset_hours in range(0, 25):
        candidate = (base + timedelta(hours=offset_hours)).replace(minute=minute)
        if candidate.hour % every_hours == 0 and candidate > local_now:
            return candidate.astimezone(timezone.utc)
    return (base + timedelta(hours=every_hours)).replace(minute=minute).astimezone(timezone.utc)


def next_daily_run(now_utc: datetime, *, hour: int, minute: int, timezone_name: str) -> datetime:
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError('invalid daily schedule time')
    tz = load_timezone(timezone_name)
    local_now = now_utc.astimezone(tz)
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def planned_jobs(now_utc: datetime | None = None) -> list[ScheduledJob]:
    settings = get_settings()
    now_utc = now_utc or datetime.now(timezone.utc)
    jobs: list[ScheduledJob] = []
    if settings.nvd_sync_modified_enabled:
        jobs.append(ScheduledJob('modified', next_interval_run(now_utc, every_hours=settings.nvd_sync_modified_every_hours, minute=settings.nvd_sync_modified_minute, timezone_name=settings.nvd_sync_timezone)))
    if settings.nvd_sync_daily_mirror_enabled:
        jobs.append(ScheduledJob('daily-mirror', next_daily_run(now_utc, hour=settings.nvd_sync_daily_mirror_hour, minute=settings.nvd_sync_daily_mirror_minute, timezone_name=settings.nvd_sync_timezone)))
    return sorted(jobs, key=lambda job: job.due_at_utc)


def run_job(name: SchedulerJobName, progress: ProgressCallback = _emit) -> dict[str, object]:
    settings = get_settings()
    current_year = datetime.now(timezone.utc).year
    if name == 'modified':
        progress('running incremental modified sync')
        modified_result = run_sync(mode='modified', from_year=settings.default_from_year, to_year=current_year)
        progress('mirroring recent feed for raw mirror completeness')
        recent_results = mirror_feeds(['recent'], force=False, progress=progress)
        recent_result = recent_results[0] if recent_results else None
        return {'mode': 'modified-plus-recent', 'modifiedSync': modified_result, 'recentMirror': recent_result.as_dict() if recent_result else None}
    if name == 'daily-mirror':
        progress('running daily raw feed mirror refresh')
        feeds = list(iter_year_feeds(settings.default_from_year, current_year)) + ['modified', 'recent']
        results = mirror_feeds(feeds, force=settings.nvd_sync_daily_mirror_force, progress=progress)
        return {'mode': 'daily-mirror', 'feedsMirrored': len(results), 'feeds': [r.feed for r in results], 'statuses': {r.feed: r.status for r in results}}
    raise ValueError(f'Unsupported scheduler job: {name}')


def run_startup_action(progress: ProgressCallback = _emit) -> None:
    settings = get_settings()
    action = settings.scheduler_run_on_startup.lower().strip()
    current_year = datetime.now(timezone.utc).year
    if action in {'', 'none', 'false', 'no'}:
        progress('startup action disabled')
        return
    if action == 'modified':
        result = run_job('modified', progress=progress)
    elif action == 'bootstrap':
        result = run_sync(mode='bootstrap', from_year=settings.default_from_year, to_year=current_year)
    elif action == 'all':
        result = run_sync(mode='all', from_year=settings.default_from_year, to_year=current_year)
    else:
        raise ValueError('SCHEDULER_RUN_ON_STARTUP must be one of: none, modified, bootstrap, all')
    progress(f'startup action complete: {json.dumps(result, sort_keys=True)}')


def run_scheduler_forever(progress: ProgressCallback = _emit) -> None:
    settings = get_settings()
    if not settings.scheduler_enabled:
        progress('scheduler disabled; exiting')
        return
    progress(f'scheduler started with timezone={settings.nvd_sync_timezone}, modified_every={settings.nvd_sync_modified_every_hours}h, modified_minute={settings.nvd_sync_modified_minute}, daily_mirror={settings.nvd_sync_daily_mirror_hour:02d}:{settings.nvd_sync_daily_mirror_minute:02d}')
    run_startup_action(progress)
    while True:
        jobs = planned_jobs(datetime.now(timezone.utc))
        if not jobs:
            time.sleep(max(1, int(settings.scheduler_max_sleep_seconds)))
            continue
        next_job = jobs[0]
        sleep_for = max(0.0, (next_job.due_at_utc - datetime.now(timezone.utc)).total_seconds())
        max_sleep = max(1, int(settings.scheduler_max_sleep_seconds))
        if sleep_for > 0:
            progress(f'next job {next_job.name} due at {next_job.due_at_utc.isoformat()} UTC')
        while sleep_for > 0:
            time.sleep(min(sleep_for, max_sleep))
            sleep_for = max(0.0, (next_job.due_at_utc - datetime.now(timezone.utc)).total_seconds())
        try:
            result = run_job(next_job.name, progress=progress)
            progress(f'job {next_job.name} complete: {json.dumps(result, sort_keys=True)}')
        except Exception as exc:  # noqa: BLE001
            progress(f'job {next_job.name} failed: {exc!r}')
            time.sleep(max_sleep)


def main() -> int:
    parser = argparse.ArgumentParser(description='Run the Docker Compose scheduler for NVD sync jobs.')
    parser.add_argument('--print-plan', action='store_true')
    parser.add_argument('--once-modified', action='store_true')
    parser.add_argument('--once-daily-mirror', action='store_true')
    args = parser.parse_args()
    if args.print_plan:
        print(json.dumps([job.as_dict() for job in planned_jobs()], indent=2, sort_keys=True)); return 0
    if args.once_modified:
        print(json.dumps(run_job('modified'), indent=2, sort_keys=True)); return 0
    if args.once_daily_mirror:
        print(json.dumps(run_job('daily-mirror'), indent=2, sort_keys=True)); return 0
    run_scheduler_forever(); return 0


if __name__ == '__main__':
    raise SystemExit(main())
