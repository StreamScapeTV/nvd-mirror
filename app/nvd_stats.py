from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.db import create_tables, session_scope
from app.models import CveDerivedStats, CveRecord, DashboardStatsSnapshot, utcnow

ProgressCallback = Callable[[str], None]
SNAPSHOT_NAME = 'nvd-stats'


def _emit(message: str) -> None:
    print(f'[nvd-stats] {datetime.now(timezone.utc).isoformat(timespec="seconds")}Z {message}', flush=True)


def _nvd_primary_metric_candidates(metrics: dict[str, Any], keys: list[str]) -> dict[str, Any] | None:
    for key in keys:
        values = metrics.get(key) or []
        if not isinstance(values, list) or not values:
            continue
        for item in values:
            source = str(item.get('source') or '').lower()
            metric_type = str(item.get('type') or '').lower()
            if source == 'nvd@nist.gov' and metric_type == 'primary':
                return item
        for item in values:
            if str(item.get('source') or '').lower() == 'nvd@nist.gov':
                return item
    return None


def _metric_severity(cve: dict[str, Any], *, version: str) -> str | None:
    metrics = cve.get('metrics') or {}
    if not isinstance(metrics, dict):
        return None
    if version == 'v3':
        metric = _nvd_primary_metric_candidates(metrics, ['cvssMetricV31', 'cvssMetricV30'])
    elif version == 'v2':
        metric = _nvd_primary_metric_candidates(metrics, ['cvssMetricV2'])
    else:
        metric = None
    if not metric:
        return None
    cvss_data = metric.get('cvssData') or {}
    severity = cvss_data.get('baseSeverity') or metric.get('baseSeverity')
    return str(severity).upper() if severity else None


def _count_cpe_matches(cve: dict[str, Any]) -> int:
    total = 0
    for config in cve.get('configurations') or []:
        if not isinstance(config, dict):
            continue
        for node in config.get('nodes') or []:
            if isinstance(node, dict) and isinstance(node.get('cpeMatch') or [], list):
                total += len(node.get('cpeMatch') or [])
    return total


def derive_cve_stats_row(item: dict[str, Any]) -> dict[str, Any] | None:
    cve = item.get('cve') or {}
    if not isinstance(cve, dict) or not cve.get('id'):
        return None
    references = cve.get('references') or []
    descriptions = cve.get('descriptions') or []
    configurations = cve.get('configurations') or []
    weaknesses = cve.get('weaknesses') or []
    return {
        'cve_id': str(cve['id']),
        'vuln_status': str(cve.get('vulnStatus') or 'unknown'),
        'source_identifier': str(cve.get('sourceIdentifier') or 'unknown'),
        'cvss_v3_severity': _metric_severity(cve, version='v3'),
        'cvss_v2_severity': _metric_severity(cve, version='v2'),
        'has_configurations': bool(configurations),
        'has_weaknesses': bool(weaknesses),
        'cpe_match_entries': _count_cpe_matches(cve),
        'reference_entries': len(references) if isinstance(references, list) else 0,
        'description_entries': len(descriptions) if isinstance(descriptions, list) else 0,
        'updated_at': utcnow(),
    }


def upsert_cve_stats_batch(db: Session, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    dialect = db.bind.dialect.name if db.bind is not None else ''
    update_columns = ['vuln_status', 'source_identifier', 'cvss_v3_severity', 'cvss_v2_severity', 'has_configurations', 'has_weaknesses', 'cpe_match_entries', 'reference_entries', 'description_entries', 'updated_at']
    if dialect == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
        stmt = insert(CveDerivedStats).values(rows)
        stmt = stmt.on_conflict_do_update(index_elements=[CveDerivedStats.cve_id], set_={key: getattr(stmt.excluded, key) for key in update_columns})
        db.execute(stmt); return
    if dialect == 'sqlite':
        from sqlalchemy.dialects.sqlite import insert
        stmt = insert(CveDerivedStats).values(rows)
        stmt = stmt.on_conflict_do_update(index_elements=[CveDerivedStats.cve_id], set_={key: getattr(stmt.excluded, key) for key in update_columns})
        db.execute(stmt); return
    for row in rows:
        db.merge(CveDerivedStats(**row))


def _severity_rows(counter: Counter[str], *, include_missing: bool = True) -> list[dict[str, Any]]:
    order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'MISSING']
    output = []
    seen = set()
    for severity in order:
        if severity == 'MISSING' and not include_missing:
            continue
        if severity in counter:
            output.append({'severity': severity, 'count': int(counter[severity])}); seen.add(severity)
    for severity, count in counter.most_common():
        if severity not in seen and (include_missing or severity != 'MISSING'):
            output.append({'severity': severity, 'count': int(count)})
    return output


def _counter_from_grouped(rows: list[tuple[Any, int]], *, missing_label: str | None = None) -> Counter[str]:
    counter: Counter[str] = Counter()
    for key, count in rows:
        label = missing_label if key is None and missing_label is not None else str(key or 'unknown')
        counter[label] += int(count or 0)
    return counter


def calculate_local_nvd_stats_from_derived(db: Session) -> dict[str, Any]:
    total = int(db.execute(select(func.count()).select_from(CveDerivedStats)).scalar_one() or 0)
    status_counts = _counter_from_grouped(db.execute(select(CveDerivedStats.vuln_status, func.count()).group_by(CveDerivedStats.vuln_status)).all())
    source_counts = _counter_from_grouped(db.execute(select(CveDerivedStats.source_identifier, func.count()).group_by(CveDerivedStats.source_identifier).order_by(func.count().desc()).limit(10)).all())
    v3_counts = _counter_from_grouped(db.execute(select(CveDerivedStats.cvss_v3_severity, func.count()).group_by(CveDerivedStats.cvss_v3_severity)).all(), missing_label='MISSING')
    v2_counts = _counter_from_grouped(db.execute(select(CveDerivedStats.cvss_v2_severity, func.count()).group_by(CveDerivedStats.cvss_v2_severity)).all(), missing_label='MISSING')

    def scalar_int(statement) -> int:
        return int(db.execute(statement).scalar_one() or 0)

    contains = {
        'cveVulnerabilities': total,
        'cpeMatchEntriesInCves': scalar_int(select(func.coalesce(func.sum(CveDerivedStats.cpe_match_entries), 0))),
        'referenceEntriesInCves': scalar_int(select(func.coalesce(func.sum(CveDerivedStats.reference_entries), 0))),
        'descriptionEntriesInCves': scalar_int(select(func.coalesce(func.sum(CveDerivedStats.description_entries), 0))),
        'cvesWithConfigurations': scalar_int(select(func.count()).select_from(CveDerivedStats).where(CveDerivedStats.has_configurations.is_(True))),
        'cvesWithWeaknesses': scalar_int(select(func.count()).select_from(CveDerivedStats).where(CveDerivedStats.has_weaknesses.is_(True))),
        'cvesWithNvdPrimaryCvssV3': total - int(v3_counts.get('MISSING', 0)),
        'cvesWithNvdPrimaryCvssV2': total - int(v2_counts.get('MISSING', 0)),
    }
    local_db_total = int(db.execute(select(func.count()).select_from(CveRecord)).scalar_one() or 0)
    coverage_missing = max(local_db_total - total, 0)
    coverage_complete = coverage_missing == 0
    incomplete_message = None if coverage_complete else f'Derived stats are incomplete: {total:,} of {local_db_total:,} CVEs have stats rows; {coverage_missing:,} CVEs still need backfill. Run: python -m app.nvd_stats backfill-missing --batch-size 500'

    if not coverage_complete:
        contains = {'cveVulnerabilities': local_db_total}
        status_rows: list[dict[str, Any]] = []
        top_sources: list[dict[str, Any]] = []
        cvss_v3 = {'rows': [], 'chartRows': [], 'scored': None, 'missing': None, 'basis': 'Exact CVSS V3 stats unavailable until derived stats backfill is complete.'}
        cvss_v2 = {'rows': [], 'chartRows': [], 'scored': None, 'missing': None, 'basis': 'Exact CVSS V2 stats unavailable until derived stats backfill is complete.'}
    else:
        status_rows = [{'status': status, 'count': int(count)} for status, count in status_counts.most_common()]
        top_sources = [{'source': source, 'count': int(count)} for source, count in source_counts.most_common(10)]
        cvss_v3 = {'rows': _severity_rows(v3_counts), 'chartRows': _severity_rows(v3_counts, include_missing=False), 'scored': int(sum(count for severity, count in v3_counts.items() if severity != 'MISSING')), 'missing': int(v3_counts.get('MISSING', 0)), 'basis': 'Exact local mirrored CVE JSON count: NVD primary CVSS v3.x metrics only'}
        cvss_v2 = {'rows': _severity_rows(v2_counts), 'chartRows': _severity_rows(v2_counts, include_missing=False), 'scored': int(sum(count for severity, count in v2_counts.items() if severity != 'MISSING')), 'missing': int(v2_counts.get('MISSING', 0)), 'basis': 'Exact local mirrored CVE JSON count: NVD primary CVSS v2 metrics only'}

    return {'generatedAt': datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'), 'local': {'totalVulnerabilities': local_db_total, 'derivedStatsRows': total, 'derivedStatsMissingRows': coverage_missing, 'statsCoverageComplete': coverage_complete, 'statsIncompleteMessage': incomplete_message, 'contains': contains, 'statusCounts': status_rows, 'topSources': top_sources, 'cvssV3': cvss_v3, 'cvssV2': cvss_v2}}


def rebuild_cve_derived_stats(db: Session, *, progress: ProgressCallback | None = None, batch_size: int = 1000) -> int:
    progress = progress or (lambda _message: None)
    result = db.execute(select(CveRecord.cve_id, CveRecord.raw_json).order_by(CveRecord.cve_id.asc()).execution_options(yield_per=batch_size, stream_results=True)).yield_per(batch_size)
    stats_batch: list[dict[str, Any]] = []
    processed = 0
    for _cve_id, raw_json in result:
        try:
            item = json.loads(raw_json)
        except Exception:  # noqa: BLE001
            continue
        row = derive_cve_stats_row(item)
        if row:
            stats_batch.append(row)
        processed += 1
        if len(stats_batch) >= batch_size:
            upsert_cve_stats_batch(db, stats_batch); db.commit(); stats_batch.clear()
        if processed % 25000 == 0:
            progress(f'backfilled exact stats for {processed} CVEs')
    if stats_batch:
        upsert_cve_stats_batch(db, stats_batch); db.commit()
    progress(f'completed exact stats backfill for {processed} CVEs')
    return processed


def backfill_missing_cve_derived_stats(db: Session, *, progress: ProgressCallback | None = None, batch_size: int = 1000) -> int:
    progress = progress or (lambda _message: None)
    processed_total = 0
    while True:
        rows = db.execute(select(CveRecord.cve_id, CveRecord.raw_json).where(~exists().where(CveDerivedStats.cve_id == CveRecord.cve_id)).order_by(CveRecord.cve_id.asc()).limit(batch_size)).all()
        if not rows:
            break
        stats_batch = []
        for _cve_id, raw_json in rows:
            try:
                item = json.loads(raw_json)
            except Exception:  # noqa: BLE001
                continue
            row = derive_cve_stats_row(item)
            if row:
                stats_batch.append(row)
        upsert_cve_stats_batch(db, stats_batch); db.commit()
        processed_total += len(rows)
        progress(f'backfilled missing exact stats for {processed_total} CVEs')
    progress(f'completed missing exact stats backfill for {processed_total} CVEs')
    return processed_total


def save_nvd_stats_snapshot(db: Session, payload: dict[str, Any], *, status: str = 'ok', error: str | None = None) -> DashboardStatsSnapshot:
    snapshot = db.get(DashboardStatsSnapshot, SNAPSHOT_NAME)
    if snapshot is None:
        snapshot = DashboardStatsSnapshot(name=SNAPSHOT_NAME, payload_json='{}'); db.add(snapshot)
    snapshot.generated_at = utcnow(); snapshot.status = status; snapshot.error = error; snapshot.payload_json = json.dumps(payload, sort_keys=True)
    db.commit(); return snapshot


def read_nvd_stats_snapshot(db: Session) -> dict[str, Any] | None:
    snapshot = db.get(DashboardStatsSnapshot, SNAPSHOT_NAME)
    if snapshot is None:
        return None
    try:
        payload = json.loads(snapshot.payload_json)
    except Exception:  # noqa: BLE001
        payload = {}
    payload['snapshot'] = {'name': snapshot.name, 'status': snapshot.status, 'error': snapshot.error, 'generatedAt': snapshot.generated_at.isoformat(timespec='milliseconds').replace('+00:00', 'Z') if snapshot.generated_at else None}
    return payload


def refresh_nvd_stats_snapshot(db: Session, *, progress: ProgressCallback | None = None) -> dict[str, Any]:
    progress = progress or _emit
    progress('refreshing exact local dashboard statistics snapshot from materialized per-CVE stats')
    try:
        payload = calculate_local_nvd_stats_from_derived(db)
        save_nvd_stats_snapshot(db, payload, status='ok', error=None)
        total = payload.get('local', {}).get('totalVulnerabilities')
        derived = payload.get('local', {}).get('derivedStatsRows')
        missing = payload.get('local', {}).get('derivedStatsMissingRows')
        if missing:
            progress(f'dashboard statistics snapshot refreshed as incomplete ({total} CVEs, derived rows={derived}, missing derived rows={missing}); exact breakdowns are hidden until backfill completes')
        else:
            progress(f'exact dashboard statistics snapshot refreshed ({total} CVEs, derived rows={derived}, missing derived rows={missing})')
        return payload
    except Exception as exc:  # noqa: BLE001
        error_payload = {'generatedAt': datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'), 'local': {'totalVulnerabilities': None}, 'error': str(exc)}
        save_nvd_stats_snapshot(db, error_payload, status='error', error=str(exc))
        progress(f'exact dashboard statistics snapshot failed: {exc!r}')
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description='Manage exact NVD dashboard statistics snapshot.')
    parser.add_argument('command', choices=['refresh', 'rebuild', 'backfill-missing'])
    parser.add_argument('--batch-size', type=int, default=1000)
    args = parser.parse_args()
    create_tables()
    with session_scope() as db:
        if args.command == 'rebuild':
            rebuilt = rebuild_cve_derived_stats(db, progress=_emit, batch_size=args.batch_size)
            payload = refresh_nvd_stats_snapshot(db, progress=_emit)
            result = {'status': 'ok', 'rebuilt': rebuilt}
        elif args.command == 'backfill-missing':
            rebuilt = backfill_missing_cve_derived_stats(db, progress=_emit, batch_size=args.batch_size)
            payload = refresh_nvd_stats_snapshot(db, progress=_emit)
            result = {'status': 'ok', 'backfilledMissing': rebuilt}
        else:
            payload = refresh_nvd_stats_snapshot(db, progress=_emit)
            result = {'status': 'ok'}
        result.update({'generatedAt': payload.get('generatedAt'), 'totalVulnerabilities': payload.get('local', {}).get('totalVulnerabilities'), 'derivedStatsRows': payload.get('local', {}).get('derivedStatsRows'), 'derivedStatsMissingRows': payload.get('local', {}).get('derivedStatsMissingRows')})
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
