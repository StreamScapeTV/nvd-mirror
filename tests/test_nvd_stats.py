from __future__ import annotations

import json

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import CveDerivedStats, CveRecord
from app.nvd_stats import backfill_missing_cve_derived_stats, calculate_local_nvd_stats_from_derived, derive_cve_stats_row
from app.utils import parse_dt


def _item(cve_id: str, status: str = 'Analyzed') -> dict:
    return {'cve': {'id': cve_id, 'sourceIdentifier': 'nvd@nist.gov', 'published': '2026-01-01T00:00:00.000', 'lastModified': '2026-01-02T00:00:00.000', 'vulnStatus': status, 'descriptions': [{'lang':'en','value':'x'}], 'references': [], 'metrics': {'cvssMetricV31': [{'source':'nvd@nist.gov','type':'Primary','cvssData':{'baseSeverity':'HIGH'}}]}}}


def test_derive_cve_stats_uses_nvd_primary_cvss() -> None:
    row = derive_cve_stats_row(_item('CVE-2026-0001'))
    assert row is not None
    assert row['cvss_v3_severity'] == 'HIGH'
    assert row['vuln_status'] == 'Analyzed'


def test_backfill_missing_is_resumable_and_complete() -> None:
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        for cve_id, status in [('CVE-2026-0001','Analyzed'),('CVE-2026-0002','Modified')]:
            item = _item(cve_id, status)
            db.add(CveRecord(cve_id=cve_id, year=2026, published=parse_dt(item['cve']['published']), last_modified=parse_dt(item['cve']['lastModified']), source_feed='2026', raw_json=json.dumps(item)))
        db.commit()
        assert backfill_missing_cve_derived_stats(db, batch_size=1) == 2
        assert backfill_missing_cve_derived_stats(db, batch_size=1) == 0
        stats = calculate_local_nvd_stats_from_derived(db)
        assert stats['local']['totalVulnerabilities'] == 2
        assert stats['local']['derivedStatsMissingRows'] == 0
        assert stats['local']['statsCoverageComplete'] is True


def test_partial_stats_are_hidden() -> None:
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        for cve_id in ('CVE-2026-0001','CVE-2026-0002'):
            item = _item(cve_id)
            db.add(CveRecord(cve_id=cve_id, year=2026, published=parse_dt(item['cve']['published']), last_modified=parse_dt(item['cve']['lastModified']), source_feed='2026', raw_json=json.dumps(item)))
        db.commit()
        backfill_missing_cve_derived_stats(db, batch_size=2)
        db.execute(delete(CveDerivedStats).where(CveDerivedStats.cve_id == 'CVE-2026-0002')); db.commit()
        stats = calculate_local_nvd_stats_from_derived(db)
        assert stats['local']['statsCoverageComplete'] is False
        assert stats['local']['statusCounts'] == []
        assert stats['local']['cvssV3']['chartRows'] == []
        assert stats['local']['contains'] == {'cveVulnerabilities': 2}
