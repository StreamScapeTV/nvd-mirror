from __future__ import annotations

import gzip
import hashlib
import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import Base
from app.models import CveDerivedStats, CveRecord, FeedImport


def test_local_feed_import_upserts_cve_and_stats(tmp_path, monkeypatch) -> None:
    from app.nvd_feed import import_feed

    item = {'cve': {'id':'CVE-2026-0001','sourceIdentifier':'nvd@nist.gov','published':'2026-01-01T00:00:00.000','lastModified':'2026-01-02T00:00:00.000','vulnStatus':'Analyzed','descriptions':[{'lang':'en','value':'x'}],'references':[],'metrics':{'cvssMetricV31':[{'source':'nvd@nist.gov','type':'Primary','cvssData':{'baseSeverity':'HIGH'}}]}}}
    payload = {'format':'NVD_CVE','version':'2.0','timestamp':'2026-07-01T00:00:00.000','totalResults':1,'resultsPerPage':1,'startIndex':0,'vulnerabilities':[item]}
    raw = json.dumps(payload, separators=(',', ':')).encode()
    gz = gzip.compress(raw)
    (tmp_path/'nvdcve-2.0-2026.json.gz').write_bytes(gz)
    (tmp_path/'nvdcve-2.0-2026.meta').write_text(f'lastModifiedDate:2026-07-01T00:00:00-04:00\nsize:{len(raw)}\nzipSize:{len(gz)+136}\ngzSize:{len(gz)}\nsha256:{hashlib.sha256(raw).hexdigest().upper()}\n')
    monkeypatch.setenv('NVD_FEED_SOURCE_MODE', 'local')
    monkeypatch.setenv('NVD_FEED_MIRROR_DIR', str(tmp_path))
    get_settings.cache_clear()

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        result = import_feed('2026', db)
        assert result['recordsImported'] == 1
        assert db.get(CveRecord, 'CVE-2026-0001') is not None
        assert db.get(CveDerivedStats, 'CVE-2026-0001').cvss_v3_severity == 'HIGH'
        assert db.get(FeedImport, '2026').status == 'ok'
    get_settings.cache_clear()
