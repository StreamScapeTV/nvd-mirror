from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from app.config import get_settings


def _feed() -> tuple[bytes, bytes, str]:
    raw = json.dumps({
        'format': 'NVD_CVE', 'version': '2.0', 'timestamp': '2026-07-01T00:00:00.000',
        'totalResults': 1, 'resultsPerPage': 1, 'startIndex': 0,
        'vulnerabilities': [{'cve': {'id': 'CVE-2026-0001'}}],
    }, separators=(',', ':')).encode()
    gz = gzip.compress(raw)
    meta = (
        'lastModifiedDate:2026-07-01T00:00:00-04:00\n'
        f'size:{len(raw)}\nzipSize:{len(gz) + 136}\ngzSize:{len(gz)}\n'
        f'sha256:{hashlib.sha256(raw).hexdigest().upper()}\n'
    )
    return raw, gz, meta


def test_mirror_feed_writes_valid_files_then_skips_unchanged(tmp_path, monkeypatch) -> None:
    import app.feed_mirror as mirror

    _raw, gz, meta = _feed()
    monkeypatch.setenv('NVD_FEED_MIRROR_DIR', str(tmp_path))
    monkeypatch.setenv('NVD_UPSTREAM_RETRIES', '2')
    get_settings.cache_clear()
    monkeypatch.setattr(mirror, 'download_upstream_meta_text', lambda feed, progress=None: meta)

    downloads: list[str] = []
    def fake_download(feed: str, destination: Path, progress=None) -> None:
        downloads.append(feed)
        destination.write_bytes(gz)
    monkeypatch.setattr(mirror, 'download_upstream_feed_file', fake_download)

    first = mirror.mirror_feed('2026')
    second = mirror.mirror_feed('2026')

    assert first.status == 'updated'
    assert second.status == 'unchanged'
    assert downloads == ['2026']
    assert mirror.local_json_path('2026').read_bytes() == gz
    assert first.validation.total_results == 1
    get_settings.cache_clear()
