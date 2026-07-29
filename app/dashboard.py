from __future__ import annotations

import gzip
import json
import tempfile
import time
from datetime import timezone
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dashboard_core import (
    dashboard_baseline, dashboard_feeds, dashboard_recent, dashboard_schedule,
    dashboard_summary, dashboard_years, feed_imports, file_info, expected_years,
    safe_dt, schedule_payload,
)
from app.feed_mirror import download_upstream_feed_file, download_upstream_meta_text, local_json_path, read_local_meta
from app.models import CveDerivedStats, CveRecord, FeedImport
from app.nvd_feed import MetaInfo, inspect_feed_file, validate_or_raise
from app.nvd_stats import read_nvd_stats_snapshot
from app.utils import iso_now, parse_dt

LIVE_META_CACHE_SECONDS = 300
_LIVE_META_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_NVD_API_TOTAL_CACHE: tuple[float, dict[str, Any]] | None = None
_NVD_CPE_API_TOTAL_CACHE: tuple[float, dict[str, Any]] | None = None
_NVD_STATS_CACHE: tuple[float, dict[str, Any]] | None = None


def _meta_fingerprint(meta: MetaInfo | None) -> tuple[Any, ...] | None:
    if meta is None:
        return None
    return (meta.last_modified_date, meta.size, meta.zip_size, meta.gz_size, (meta.sha256 or '').upper())


def _fetch_live_meta(feed: str, *, force: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    cached = _LIVE_META_CACHE.get(feed)
    if not force and cached and now - cached[0] < LIVE_META_CACHE_SECONDS:
        return dict(cached[1], cacheHit=True)
    try:
        text = download_upstream_meta_text(feed)
        payload = {'reachable': True, 'error': None, 'meta': MetaInfo.from_text(text).as_dict(), 'checkedAt': iso_now(), 'cacheHit': False}
    except Exception as exc:  # noqa: BLE001
        payload = {'reachable': False, 'error': str(exc), 'meta': None, 'checkedAt': iso_now(), 'cacheHit': False}
    _LIVE_META_CACHE[feed] = (now, payload)
    return payload


def _meta_from_payload(payload: dict[str, Any] | None) -> MetaInfo | None:
    if not payload:
        return None
    return MetaInfo(last_modified_date=payload.get('lastModifiedDate'), size=payload.get('size'), zip_size=payload.get('zipSize'), gz_size=payload.get('gzSize'), sha256=(payload.get('sha256') or '').upper() or None)


def _live_feed_row(feed: str, feed_import: FeedImport | None, *, force: bool = False) -> dict[str, Any]:
    live = _fetch_live_meta(feed, force=force)
    try:
        local = read_local_meta(feed)
    except Exception:  # noqa: BLE001
        local = None
    live_meta = _meta_from_payload(live.get('meta'))
    matches = live_meta is not None and local is not None and _meta_fingerprint(live_meta) == _meta_fingerprint(local)
    live_dt = parse_dt(live_meta.last_modified_date) if live_meta and live_meta.last_modified_date else None
    local_dt = parse_dt(local.last_modified_date) if local and local.last_modified_date else None
    imported = bool(feed_import and local and (feed_import.sha256 or '').upper() == (local.sha256 or '').upper())
    if local is None:
        status = 'local-mirror-missing'
    elif matches and imported:
        status = 'up-to-date-at-last-import'
    elif matches:
        status = 'local-mirror-matches-live'
    elif live_dt and (not local_dt or live_dt > local_dt):
        status = 'live-meta-newer-than-local-mirror'
    elif not live.get('reachable'):
        status = 'live-meta-unavailable'
    else:
        status = 'live-meta-differs-from-local-mirror'
    differences = []
    if live_meta or local:
        names = ['lastModifiedDate', 'size', 'zipSize', 'gzSize', 'sha256']
        live_dict = live_meta.as_dict() if live_meta else {}
        local_dict = local.as_dict() if local else {}
        differences = [name for name in names if live_dict.get(name) != local_dict.get(name)]
    return {
        'feed': feed,
        'status': status,
        'live': live,
        'localMirror': {'available': local is not None, 'meta': local.as_dict() if local else None, 'file': file_info(local_json_path(feed))},
        'databaseImport': None if feed_import is None else {'importedAt': safe_dt(feed_import.imported_at), 'recordsImported': feed_import.records_imported, 'sha256': feed_import.sha256},
        'liveMetaMatchesLocalMirror': matches,
        'liveMetaNewerThanLocalMirror': bool(local is not None and live_dt and (not local_dt or live_dt > local_dt)),
        'localMirrorImportedIntoDatabase': imported,
        'metaDifferences': differences,
    }


def dashboard_live_meta(db: Session, *, include_years: bool = False, force_refresh: bool = False) -> dict[str, Any]:
    imports = feed_imports(db)
    feeds = ['modified', 'recent'] + ([str(year) for year in expected_years()] if include_years else [])
    rows = [_live_feed_row(feed, imports.get(feed), force=force_refresh) for feed in feeds]
    changed = [row['feed'] for row in rows if row['liveMetaNewerThanLocalMirror']]
    return {'generatedAt': iso_now(), 'feeds': rows, 'summary': {'changedFeeds': changed, 'allLiveMetaMatchLocalMirror': all(row['liveMetaMatchesLocalMirror'] for row in rows if row['live']['reachable'])}, 'schedule': schedule_payload()}


def _requests_verify_setting() -> bool | str:
    settings = get_settings()
    return settings.upstream_ca_bundle or settings.upstream_verify_tls


def _live_api_total(cache_name: str, url: str, *, force: bool = False) -> dict[str, Any]:
    global _NVD_API_TOTAL_CACHE, _NVD_CPE_API_TOTAL_CACHE
    settings = get_settings()
    cache = _NVD_API_TOTAL_CACHE if cache_name == 'cve' else _NVD_CPE_API_TOTAL_CACHE
    now = time.monotonic()
    ttl = max(0, int(settings.live_nvd_total_cache_ttl_seconds or 0))
    if not force and cache and now - cache[0] < ttl:
        return dict(cache[1], cacheHit=True)
    headers = {'User-Agent': settings.nvd_user_agent or f'{settings.app_name}/{settings.app_version}', 'Accept': 'application/json'}
    if settings.nvd_api_key:
        headers['apiKey'] = settings.nvd_api_key
    try:
        response = requests.get(url, params={'resultsPerPage': 1, 'startIndex': 0}, headers=headers, timeout=settings.request_timeout_seconds, verify=_requests_verify_setting())
        response.raise_for_status()
        body = response.json()
        payload = {'reachable': True, 'error': None, 'source': url, 'checkedAt': iso_now(), 'cacheHit': False, 'cacheTtlSeconds': ttl, 'totalResults': int(body.get('totalResults') or 0), 'resultsPerPage': body.get('resultsPerPage'), 'startIndex': body.get('startIndex'), 'timestamp': body.get('timestamp')}
    except Exception as exc:  # noqa: BLE001
        payload = {'reachable': False, 'error': str(exc), 'source': url, 'checkedAt': iso_now(), 'cacheHit': False, 'cacheTtlSeconds': ttl, 'totalResults': None}
    if cache_name == 'cve':
        _NVD_API_TOTAL_CACHE = (now, payload)
    else:
        _NVD_CPE_API_TOTAL_CACHE = (now, payload)
    return payload


def _comparison(local_total: int, live_total: Any) -> dict[str, Any]:
    if live_total is None:
        return {'localMinusLive': None, 'status': 'live-total-unavailable', 'message': 'Live NVD API total is unavailable.'}
    delta = local_total - int(live_total)
    if delta == 0:
        return {'localMinusLive': 0, 'status': 'matches-live-nvd-api', 'message': 'Local DB total matches the live NVD API total.'}
    if delta < 0:
        return {'localMinusLive': delta, 'status': 'behind-live-nvd-api', 'message': f'Local DB is behind the live NVD API by {abs(delta):,} CVEs.'}
    return {'localMinusLive': delta, 'status': 'ahead-of-live-nvd-api', 'message': f'Local DB has {delta:,} more CVEs than the live NVD API total.'}


def _hide_partial_stats(payload: dict[str, Any], local_total: int, derived: int) -> dict[str, Any]:
    missing = max(local_total - derived, 0)
    local = dict(payload.get('local') or {})
    local.update({'totalVulnerabilities': local_total, 'derivedStatsRows': derived, 'derivedStatsMissingRows': missing, 'statsCoverageComplete': missing == 0, 'statsIncompleteMessage': None if missing == 0 else f'Exact local breakdowns are unavailable until {missing:,} missing derived stats rows are backfilled.'})
    if missing:
        local.update({'contains': {'cveVulnerabilities': local_total}, 'statusCounts': [], 'topSources': [], 'cvssV3': {'rows': [], 'chartRows': [], 'scored': None, 'missing': None, 'basis': 'Unavailable until derived stats backfill is complete.'}, 'cvssV2': {'rows': [], 'chartRows': [], 'scored': None, 'missing': None, 'basis': 'Unavailable until derived stats backfill is complete.'}})
    payload = dict(payload)
    payload['local'] = local
    return payload


def dashboard_nvd_stats(db: Session, *, force_live_total: bool = False, force_recalculate: bool = False) -> dict[str, Any]:
    del force_recalculate
    local_total = int(db.execute(select(func.count()).select_from(CveRecord)).scalar_one() or 0)
    derived = int(db.execute(select(func.count()).select_from(CveDerivedStats)).scalar_one() or 0)
    snapshot = read_nvd_stats_snapshot(db) or {'generatedAt': None, 'snapshot': {'status': 'missing'}}
    snapshot = _hide_partial_stats(snapshot, local_total, derived)
    settings = get_settings()
    live_nvd = _live_api_total('cve', settings.nvd_api_cves_url, force=force_live_total)
    live_cpe = _live_api_total('cpe', settings.nvd_api_cpes_url, force=force_live_total)
    return {**snapshot, 'liveNvd': live_nvd, 'liveCpe': live_cpe, 'comparison': _comparison(local_total, live_nvd.get('totalResults')), 'notes': {'localMetricsDescription': 'Only exact local metrics are shown. Partial coverage is hidden, not estimated.'}}


def dashboard_upstream_modified(db: Session, *, inspect: bool = False) -> dict[str, Any]:
    imports = feed_imports(db)
    row = _live_feed_row('modified', imports.get('modified'), force=True)
    checks = {'upstreamMetaMatchesLocalMirror': row['liveMetaMatchesLocalMirror'], 'localMirrorImportedIntoDatabase': row['localMirrorImportedIntoDatabase']}
    if row['liveMetaMatchesLocalMirror'] and row['localMirrorImportedIntoDatabase']:
        checks['pendingStatus'] = 'up-to-date'
    elif row['liveMetaMatchesLocalMirror']:
        checks['pendingStatus'] = 'local-mirror-not-imported'
    else:
        checks['pendingStatus'] = 'upstream-meta-differs'
    payload: dict[str, Any] = {'generatedAt': iso_now(), 'upstream': row['live'], 'localMirror': row['localMirror'], 'databaseImport': row['databaseImport'], 'checks': checks, 'schedule': schedule_payload(), 'inspection': None}
    if not inspect or not row['live']['reachable']:
        return payload
    meta = _meta_from_payload(row['live'].get('meta'))
    if meta is None:
        return payload
    with tempfile.NamedTemporaryFile('wb', suffix='.json.gz', delete=False) as fh:
        temp_path = Path(fh.name)
    try:
        download_upstream_feed_file('modified', temp_path)
        validation = inspect_feed_file('modified', temp_path, meta)
        validate_or_raise(validation)
        with gzip.open(temp_path, 'rt', encoding='utf-8') as fh:
            items = json.load(fh).get('vulnerabilities') or []
        ids = [item.get('cve', {}).get('id') for item in items if item.get('cve', {}).get('id')]
        existing = {record.cve_id: record for record in db.execute(select(CveRecord).where(CveRecord.cve_id.in_(ids))).scalars().all()} if ids else {}
        not_in_db = 0
        stale = 0
        for item in items:
            cve = item.get('cve') or {}
            cve_id = cve.get('id')
            if not cve_id:
                continue
            record = existing.get(cve_id)
            if record is None:
                not_in_db += 1
                continue
            incoming = parse_dt(cve.get('lastModified'))
            current = record.last_modified
            if incoming and (current is None or incoming > (current if current.tzinfo else current.replace(tzinfo=timezone.utc))):
                stale += 1
        pending = {'feedRecords': len(ids), 'notInDatabase': not_in_db, 'staleExistingRecords': stale, 'alreadyCurrent': len(ids) - not_in_db - stale, 'pendingUpserts': not_in_db + stale}
        payload['inspection'] = {'validation': validation.as_dict(), 'pending': pending}
        payload['checks']['pendingStatus'] = 'pending-upserts-after-inspection' if pending['pendingUpserts'] else 'current-after-inspection'
        return payload
    finally:
        temp_path.unlink(missing_ok=True)
