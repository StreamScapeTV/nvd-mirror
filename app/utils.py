from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from dateutil import parser as date_parser

CVE_YEAR_RE = re.compile(r'^CVE-(\d{4})-')


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = date_parser.isoparse(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def cve_year(cve_id: str | None) -> int | None:
    if not cve_id:
        return None
    match = CVE_YEAR_RE.match(cve_id)
    if not match:
        return None
    return int(match.group(1))


def remove_none_values(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}
