from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import re

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import create_tables, get_db
from app.models import CveRecord
from app.nvd_api import query_nvd_cves
from app.dashboard import (
    dashboard_baseline,
    dashboard_feeds,
    dashboard_live_meta,
    dashboard_nvd_stats,
    dashboard_recent,
    dashboard_schedule,
    dashboard_summary,
    dashboard_upstream_modified,
    dashboard_years,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description='Self-hosted NVD JSON feed mirror with an NVD CVE API-compatible read endpoint.',
    lifespan=lifespan,
)


@app.get('/dashboard', include_in_schema=False)
def dashboard_page() -> FileResponse:
    return FileResponse(Path(__file__).parent / 'static' / 'dashboard.html', media_type='text/html')


@app.get('/', include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url='/dashboard')


@app.get('/dashboard/api/summary')
def dashboard_summary_api(db: Session = Depends(get_db)) -> dict[str, object]:
    return dashboard_summary(db)


@app.get('/dashboard/api/years')
def dashboard_years_api(validate: bool = Query(default=False), db: Session = Depends(get_db)) -> dict[str, object]:
    return dashboard_years(db, full_validation=validate)


@app.get('/dashboard/api/recent')
def dashboard_recent_api(limit: int = Query(default=25, ge=1, le=100), db: Session = Depends(get_db)) -> dict[str, object]:
    return dashboard_recent(db, limit=limit)


@app.get('/dashboard/api/feeds')
def dashboard_feeds_api(validate: bool = Query(default=False), db: Session = Depends(get_db)) -> dict[str, object]:
    return dashboard_feeds(db, full_validation=validate)


@app.get('/dashboard/api/baseline')
def dashboard_baseline_api(db: Session = Depends(get_db)) -> dict[str, object]:
    return dashboard_baseline(db)


@app.get('/dashboard/api/schedule')
def dashboard_schedule_api() -> dict[str, object]:
    return dashboard_schedule()


@app.get('/dashboard/api/live-meta')
def dashboard_live_meta_api(includeYears: bool = Query(default=False), force: bool = Query(default=False), db: Session = Depends(get_db)) -> dict[str, object]:
    return dashboard_live_meta(db, include_years=includeYears, force_refresh=force)


@app.get('/dashboard/api/nvd-stats')
def dashboard_nvd_stats_api(forceLive: bool = Query(default=False), forceRecalculate: bool = Query(default=False), db: Session = Depends(get_db)) -> dict[str, object]:
    return dashboard_nvd_stats(db, force_live_total=forceLive, force_recalculate=forceRecalculate)


@app.get('/dashboard/api/upstream/modified')
def dashboard_upstream_modified_api(inspect: bool = Query(default=False), db: Session = Depends(get_db)) -> dict[str, object]:
    return dashboard_upstream_modified(db, inspect=inspect)


@app.get('/health')
def health() -> dict[str, str]:
    return {'status': 'ok'}


@app.get('/ready')
def ready(db: Session = Depends(get_db)) -> dict[str, str | int]:
    db.execute(select(func.count()).select_from(CveRecord)).scalar_one()
    return {'status': 'ready'}


_MIRROR_FILE_RE = re.compile(r'^nvdcve-2\.0-(modified|recent|[0-9]{4})\.(meta|json\.gz)$')


@app.get('/mirror/nvd/{filename}', include_in_schema=True)
def mirror_nvd_file(filename: str) -> FileResponse:
    if not _MIRROR_FILE_RE.match(filename):
        raise HTTPException(status_code=404, detail='NVD mirror file not found')
    from app.feed_mirror import mirror_dir
    path = mirror_dir() / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail='NVD mirror file not found')
    media_type = 'text/plain' if filename.endswith('.meta') else 'application/gzip'
    return FileResponse(path=Path(path), media_type=media_type, filename=filename)


@app.get('/rest/json/cves/2.0')
@app.get('/rest/json/cves/2.0/', include_in_schema=False)
def nvd_cves_2(
    request: Request,
    startIndex: int = Query(default=0, ge=0),
    StartIndex: int | None = Query(default=None, ge=0, include_in_schema=False),
    resultsPerPage: int = Query(default=2000, ge=1),
    cveId: str | None = None,
    pubStartDate: str | None = None,
    pubEndDate: str | None = None,
    lastModStartDate: str | None = None,
    lastModEndDate: str | None = None,
    keywordSearch: str | None = None,
    cpeName: str | None = None,
    virtualMatchString: str | None = None,
    noRejected: bool = False,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    effective_start_index = startIndex
    if 'startIndex' not in request.query_params and StartIndex is not None:
        effective_start_index = StartIndex
    return query_nvd_cves(
        db,
        start_index=effective_start_index,
        results_per_page=resultsPerPage,
        cve_id=cveId,
        pub_start_date=pubStartDate,
        pub_end_date=pubEndDate,
        last_mod_start_date=lastModStartDate,
        last_mod_end_date=lastModEndDate,
        keyword_search=keywordSearch,
        cpe_name=cpeName,
        virtual_match_string=virtualMatchString,
        no_rejected=noRejected,
    )
