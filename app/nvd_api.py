from __future__ import annotations

import json
from typing import Any

from sqlalchemy import and_, func, not_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CveRecord
from app.utils import iso_now, parse_dt


def _like_pattern(value: str) -> str:
    return f'%{value}%'


def query_nvd_cves(
    db: Session,
    *,
    start_index: int = 0,
    results_per_page: int = 2000,
    cve_id: str | None = None,
    pub_start_date: str | None = None,
    pub_end_date: str | None = None,
    last_mod_start_date: str | None = None,
    last_mod_end_date: str | None = None,
    keyword_search: str | None = None,
    cpe_name: str | None = None,
    virtual_match_string: str | None = None,
    no_rejected: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    start_index = max(0, int(start_index or 0))
    requested = max(1, int(results_per_page or settings.max_results_per_page))
    limit = min(requested, settings.max_results_per_page)

    if cve_id:
        normalized_cve_id = cve_id.upper()
        record = db.get(CveRecord, normalized_cve_id)
        total = 1 if record is not None else 0
        records = [record] if record is not None and start_index == 0 else []
        return {
            'resultsPerPage': len(records),
            'startIndex': start_index,
            'totalResults': total,
            'format': 'NVD_CVE',
            'version': '2.0',
            'timestamp': iso_now(),
            'vulnerabilities': [json.loads(record.raw_json) for record in records],
        }

    filters = []
    if pub_start_date:
        filters.append(CveRecord.published >= parse_dt(pub_start_date))
    if pub_end_date:
        filters.append(CveRecord.published <= parse_dt(pub_end_date))
    if last_mod_start_date:
        filters.append(CveRecord.last_modified >= parse_dt(last_mod_start_date))
    if last_mod_end_date:
        filters.append(CveRecord.last_modified <= parse_dt(last_mod_end_date))
    if keyword_search:
        filters.append(CveRecord.raw_json.ilike(_like_pattern(keyword_search)))
    if cpe_name:
        filters.append(CveRecord.raw_json.ilike(_like_pattern(cpe_name)))
    if virtual_match_string:
        filters.append(CveRecord.raw_json.ilike(_like_pattern(virtual_match_string)))
    if no_rejected:
        filters.append(not_(CveRecord.raw_json.ilike('%Rejected%')))

    where_clause = and_(*filters) if filters else None
    count_stmt = select(func.count()).select_from(CveRecord)
    if where_clause is not None:
        count_stmt = count_stmt.where(where_clause)
    total = int(db.execute(count_stmt).scalar_one())

    stmt = select(CveRecord)
    if where_clause is not None:
        stmt = stmt.where(where_clause)
    if last_mod_start_date or last_mod_end_date:
        stmt = stmt.order_by(CveRecord.last_modified.desc(), CveRecord.cve_id.desc())
    else:
        stmt = stmt.order_by(CveRecord.cve_id.asc())
    stmt = stmt.offset(start_index).limit(limit)
    records = list(db.execute(stmt).scalars().all())

    return {
        'resultsPerPage': len(records),
        'startIndex': start_index,
        'totalResults': total,
        'format': 'NVD_CVE',
        'version': '2.0',
        'timestamp': iso_now(),
        'vulnerabilities': [json.loads(record.raw_json) for record in records],
    }
