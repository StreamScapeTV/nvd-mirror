from __future__ import annotations

import gzip
import hashlib
import json
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import CveDerivedStats, CveRecord, FeedImport


def test_local_feed_import_upserts_cve_and_stats(tmp_path, monkeypatch) -> None:
    import app.feed_mirror as feed_mirror
    import app.nvd_feed as nvd_feed

    item = {'cve': {'id':'CVE-2026-0001','sourceIdentifier':'nvd@nist.gov','published':'2026-01-01T00:00:00.000','lastModified':'2026-01-02T00:00:00.000','vulnStatus':'Analyzed','descriptions':[{'lang':'en','value':'x'}],'references':[],'metrics':{'cvssMetricV31':[{'source':'nvd@nist.gov','type':'Primary','cvssData':{'baseSeverity':'HIGH'}}]}}}
    payload = {'format':'NVD_CVE','version':'2.0','timestamp':'2026-07-01T00:00:00.000','totalResults':1,'resultsPerPage':1,'startIndex':0,'vulnerabilities':[item]}
    raw = json.dumps(payload, separators=(',', ':')).encode()
    gz = gzip.compress(raw)
    (tmp_path/'nvdcve-2.0-2026.json.gz').write_bytes(gz)
    (tmp_path/'nvdcve-2.0-2026.meta').write_text(f'lastModifiedDate:2026-07-01T00:00:00-04:00\nsize:{len(raw)}\nzipSize:{len(gz)+136}\ngzSize:{len(gz)}\nsha256:{hashlib.sha256(raw).hexdigest().upper()}\n')

    settings = SimpleNamespace(
        nvd_feed_source_mode='local',
        nvd_feed_mirror_dir=str(tmp_path),
        validate_meta=True,
        validate_gz_size=True,
        validate_uncompressed_size=True,
        validate_uncompressed_sha256=True,
    )
    monkeypatch.setattr(nvd_feed, 'get_settings', lambda: settings)
    monkeypatch.setattr(feed_mirror, 'get_settings', lambda: settings)

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        result = nvd_feed.import_feed('2026', db)
        assert result['recordsImported'] == 1
        assert db.get(CveRecord, 'CVE-2026-0001') is not None
        assert db.get(CveDerivedStats, 'CVE-2026-0001').cvss_v3_severity == 'HIGH'
        assert db.get(FeedImport, '2026').status == 'ok'
