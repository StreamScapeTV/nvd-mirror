from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.feed_mirror import local_json_path, local_meta_path, read_local_meta
from app.models import CveRecord, FeedImport
from app.nvd_feed import inspect_feed_file, validate_or_raise
from app.scheduler import planned_jobs
from app.utils import iso_now

BASELINE_FILE = Path(__file__).parent / 'baselines' / 'nvd_year_feed_baseline_2026-06-28.json'
RAW_ONLY_FEEDS = {'recent'}


def safe_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def file_info(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {'exists': False, 'path': str(path)}
    stat = path.stat()
    return {'exists': True, 'path': str(path), 'bytes': stat.st_size, 'modifiedAt': safe_dt(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc))}


def load_baseline() -> dict[str, Any]:
    if not BASELINE_FILE.exists():
        return {'snapshotDate': None, 'minimumTotalResults': 0, 'years': {}}
    return json.loads(BASELINE_FILE.read_text(encoding='utf-8'))


def expected_years() -> list[int]:
    return list(range(int(get_settings().default_from_year), datetime.now(timezone.utc).year + 1))


def count_by_year(db: Session) -> dict[int, int]:
    rows = db.execute(select(CveRecord.year, func.count()).group_by(CveRecord.year)).all()
    result: dict[int, int] = {}
    for year, count in rows:
        if year is None:
            continue
        bucket = 2002 if int(year) <= 2002 else int(year)
        result[bucket] = result.get(bucket, 0) + int(count)
    return result


def feed_imports(db: Session) -> dict[str, FeedImport]:
    return {row.feed: row for row in db.execute(select(FeedImport)).scalars().all()}


def feed_validation(feed: str, *, full_validation: bool = False) -> dict[str, Any]:
    meta_path = local_meta_path(feed)
    json_path = local_json_path(feed)
    payload: dict[str, Any] = {'feed': feed, 'metaFile': file_info(meta_path), 'jsonFile': file_info(json_path), 'available': meta_path.exists() and json_path.exists(), 'valid': False, 'quickCheckOnly': not full_validation, 'meta': None, 'validation': None, 'error': None}
    if not payload['available']:
        return payload
    try:
        meta = read_local_meta(feed)
        size = json_path.stat().st_size
        quick_match = meta.gz_size is None or size == meta.gz_size
        payload['meta'] = meta.as_dict()
        payload['validation'] = {'feed': feed, 'gzipBytes': size, 'gzipSizeMatchesMeta': None if meta.gz_size is None else quick_match, 'gzipOk': None, 'uncompressedBytes': None, 'uncompressedSha256': None, 'uncompressedSizeMatchesMeta': None, 'uncompressedSha256MatchesMeta': None, 'format': None, 'version': None, 'totalResults': None, 'arrayLength': None, 'timestamp': None}
        payload['valid'] = bool(quick_match)
        if full_validation:
            validation = inspect_feed_file(feed, json_path, meta)
            validate_or_raise(validation)
            payload.update(valid=True, quickCheckOnly=False, validation=validation.as_dict())
    except Exception as exc:  # noqa: BLE001
        payload['error'] = str(exc)
        payload['valid'] = False
    return payload


def feed_status(feed: str, feed_import: FeedImport | None = None, database_count: int | None = None, *, full_validation: bool = False) -> dict[str, Any]:
    validation = feed_validation(feed, full_validation=full_validation or feed in RAW_ONLY_FEEDS)
    details = validation.get('validation') or {}
    total = details.get('totalResults')
    if total is None and feed_import is not None:
        total = feed_import.records_imported
    array_length = details.get('arrayLength')
    return {
        'feed': feed,
        'databaseCount': database_count,
        'databaseImportApplicable': feed not in RAW_ONLY_FEEDS,
        'mirrorValid': bool(validation.get('valid')),
        'mirrorTotalResults': total,
        'mirrorArrayLength': array_length,
        'mirrorComplete': total is not None and array_length is not None and total == array_length,
        'mirror': validation,
        'lastImport': None if feed_import is None else {'feed': feed_import.feed, 'status': feed_import.status, 'recordsImported': feed_import.records_imported, 'lastModifiedDate': feed_import.last_modified_date, 'size': feed_import.size, 'gzSize': feed_import.gz_size, 'sha256': feed_import.sha256, 'importedAt': safe_dt(feed_import.imported_at), 'error': feed_import.error},
    }


def schedule_payload() -> dict[str, Any]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    jobs = []
    for job in planned_jobs(now):
        due = job.due_at_utc.astimezone(timezone.utc)
        jobs.append({'name': job.name, 'dueAtUtc': safe_dt(due), 'secondsUntilDue': max(0, int((due - now).total_seconds()))})
    modified = next((item for item in jobs if item['name'] == 'modified'), None)
    daily = next((item for item in jobs if item['name'] == 'daily-mirror'), None)
    return {'enabled': settings.scheduler_enabled, 'timezone': settings.nvd_sync_timezone, 'modified': {'enabled': settings.nvd_sync_modified_enabled, 'everyHours': settings.nvd_sync_modified_every_hours, 'minute': settings.nvd_sync_modified_minute, 'nextRun': modified}, 'dailyMirror': {'enabled': settings.nvd_sync_daily_mirror_enabled, 'hour': settings.nvd_sync_daily_mirror_hour, 'minute': settings.nvd_sync_daily_mirror_minute, 'force': settings.nvd_sync_daily_mirror_force, 'nextRun': daily}, 'jobs': jobs}


def historical_import_state(db: Session, imports: dict[str, FeedImport]) -> dict[str, Any]:
    years = expected_years()
    imported = [year for year in years if imports.get(str(year)) and imports[str(year)].status == 'ok']
    missing = [year for year in years if year not in imported]
    yearly_total = sum(int(imports[str(year)].records_imported) for year in imported)
    database_total = int(db.execute(select(func.count()).select_from(CveRecord)).scalar_one() or 0)
    return {'expectedYears': years, 'importedYears': imported, 'missingYears': missing, 'yearlyImportCount': len(imported), 'yearlyImportTotal': yearly_total, 'databaseTotal': database_total, 'databaseMinusYearlyMirror': database_total - yearly_total, 'complete': not missing}


def baseline_summary(db: Session) -> dict[str, Any]:
    baseline = load_baseline()
    total = int(db.execute(select(func.count()).select_from(CveRecord)).scalar_one() or 0)
    minimum = int(baseline.get('minimumTotalResults') or 0)
    return {'purpose': 'offline-regression-only', 'snapshotDate': baseline.get('snapshotDate'), 'minimumTotalResults': minimum, 'databaseTotal': total, 'delta': total - minimum, 'meetsTotalMinimum': total >= minimum}


def dashboard_summary(db: Session) -> dict[str, Any]:
    settings = get_settings()
    imports = feed_imports(db)
    total = int(db.execute(select(func.count()).select_from(CveRecord)).scalar_one() or 0)
    return {'generatedAt': iso_now(), 'application': settings.app_name, 'database': {'totalVulnerabilities': total, 'earliestPublished': safe_dt(db.execute(select(func.min(CveRecord.published))).scalar_one()), 'latestPublished': safe_dt(db.execute(select(func.max(CveRecord.published))).scalar_one()), 'latestModified': safe_dt(db.execute(select(func.max(CveRecord.last_modified))).scalar_one()), 'latestImported': safe_dt(db.execute(select(func.max(CveRecord.imported_at))).scalar_one())}, 'historicalImport': historical_import_state(db, imports), 'sync': {'modifiedFeed': feed_status('modified', imports.get('modified')), 'recentFeed': feed_status('recent', imports.get('recent')), 'schedule': schedule_payload()}, 'baseline': baseline_summary(db), 'upstream': {'feedBaseUrl': settings.nvd_feed_upstream_base_url or settings.nvd_mirror_base_url, 'sourceMode': settings.nvd_feed_source_mode, 'mirrorDirectory': settings.nvd_feed_mirror_dir}}


def dashboard_years(db: Session, *, full_validation: bool = False) -> dict[str, Any]:
    counts = count_by_year(db)
    imports = feed_imports(db)
    rows = [feed_status(str(year), imports.get(str(year)), counts.get(year, 0), full_validation=full_validation) | {'year': year} for year in expected_years()]
    return {'generatedAt': iso_now(), 'years': rows}


def dashboard_recent(db: Session, *, limit: int = 25) -> dict[str, Any]:
    records = db.execute(select(CveRecord).order_by(CveRecord.last_modified.desc(), CveRecord.cve_id.desc()).limit(limit)).scalars().all()
    items = []
    for record in records:
        try:
            cve = json.loads(record.raw_json).get('cve') or {}
        except Exception:  # noqa: BLE001
            cve = {}
        description = next((item.get('value') or '' for item in cve.get('descriptions') or [] if item.get('lang') == 'en'), '')
        items.append({'id': record.cve_id, 'year': record.year, 'published': safe_dt(record.published), 'lastModified': safe_dt(record.last_modified), 'sourceFeed': record.source_feed, 'vulnStatus': cve.get('vulnStatus'), 'description': description})
    return {'generatedAt': iso_now(), 'limit': limit, 'items': items}


def dashboard_feeds(db: Session, *, full_validation: bool = False) -> dict[str, Any]:
    imports = feed_imports(db)
    feeds = ['modified', 'recent'] + [str(year) for year in expected_years()]
    return {'generatedAt': iso_now(), 'feeds': [feed_status(feed, imports.get(feed), full_validation=full_validation) for feed in feeds]}


def dashboard_baseline(db: Session) -> dict[str, Any]:
    counts = count_by_year(db)
    baseline = load_baseline()
    years = []
    for year_text, info in sorted((baseline.get('years') or {}).items(), key=lambda item: int(item[0])):
        year = int(year_text)
        minimum = int(info.get('minimumTotalResults') or 0)
        actual = counts.get(year, 0)
        years.append({'year': year, 'databaseCount': actual, 'minimumTotalResults': minimum, 'delta': actual - minimum, 'meetsBaseline': actual >= minimum, 'sampleCveId': info.get('sampleCveId'), 'timestamp': info.get('timestamp')})
    total = sum(counts.values())
    return {'generatedAt': iso_now(), 'purpose': 'offline-regression-only', 'baseline': baseline, 'databaseTotal': total, 'meetsTotalMinimum': total >= int(baseline.get('minimumTotalResults') or 0), 'years': years}


def dashboard_schedule() -> dict[str, Any]:
    return {'generatedAt': iso_now(), 'schedule': schedule_payload()}
