from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from app.config import get_settings


def _payload(cve_id: str) -> tuple[bytes, bytes, str]:
    raw = json.dumps({'format':'NVD_CVE','version':'2.0','timestamp':'2026-07-01T00:00:00.000','totalResults':1,'resultsPerPage':1,'startIndex':0,'vulnerabilities':[{'cve':{'id':cve_id}}]}, separators=(',', ':')).encode()
    gz = gzip.compress(raw)
    meta = f'lastModifiedDate:2026-07-01T00:00:00-04:00\nsize:{len(raw)}\nzipSize:{len(gz)+136}\ngzSize:{len(gz)}\nsha256:{hashlib.sha256(raw).hexdigest().upper()}\n'
    return raw, gz, meta


def test_mirror_refetches_meta_after_validation_mismatch(tmp_path, monkeypatch) -> None:
    import app.feed_mirror as mirror

    _raw1, gz1, meta1 = _payload('CVE-2026-0001')
    _raw2, gz2, meta2 = _payload('CVE-2026-0002')
    monkeypatch.setenv('NVD_FEED_MIRROR_DIR', str(tmp_path))
    monkeypatch.setenv('NVD_UPSTREAM_RETRIES', '2')
    monkeypatch.setenv('NVD_UPSTREAM_RETRY_BACKOFF_SECONDS', '0')
    get_settings.cache_clear()
    metas = iter([meta1, meta2])
    payloads = iter([gz2, gz2])
    monkeypatch.setattr(mirror, 'download_upstream_meta_text', lambda feed, progress=None: next(metas))
    monkeypatch.setattr(mirror, 'download_upstream_feed_file', lambda feed, destination, progress=None: destination.write_bytes(next(payloads)))

    result = mirror.mirror_feed('modified')

    assert result.status == 'updated'
    assert result.meta.sha256 == hashlib.sha256(_raw2).hexdigest().upper()
    assert result.validation.total_results == 1
    get_settings.cache_clear()
