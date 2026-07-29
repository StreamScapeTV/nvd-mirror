from __future__ import annotations

import gzip
import hashlib
import json

import pytest

from app.nvd_feed import MetaInfo, inspect_feed_file, validate_or_raise


def _payload() -> bytes:
    return json.dumps({
        'format': 'NVD_CVE',
        'version': '2.0',
        'timestamp': '2026-07-01T00:00:00.000',
        'totalResults': 1,
        'resultsPerPage': 1,
        'startIndex': 0,
        'vulnerabilities': [{'cve': {'id': 'CVE-2026-0001'}}],
    }, separators=(',', ':')).encode()


def test_feed_file_matches_meta(tmp_path) -> None:
    raw = _payload()
    path = tmp_path / 'feed.json.gz'
    path.write_bytes(gzip.compress(raw))
    meta = MetaInfo('2026-07-01T00:00:00-04:00', len(raw), None, path.stat().st_size, hashlib.sha256(raw).hexdigest().upper())
    result = inspect_feed_file('2026', path, meta)
    validate_or_raise(result)
    assert result.gzip_ok is True
    assert result.gzip_size_matches_meta is True
    assert result.uncompressed_size_matches_meta is True
    assert result.uncompressed_sha256_matches_meta is True
    assert result.total_results == result.array_length == 1


def test_feed_file_rejects_wrong_meta(tmp_path) -> None:
    raw = _payload()
    path = tmp_path / 'feed.json.gz'
    path.write_bytes(gzip.compress(raw))
    meta = MetaInfo('2026-07-01T00:00:00-04:00', len(raw) + 1, None, path.stat().st_size + 1, '0' * 64)
    result = inspect_feed_file('2026', path, meta)
    with pytest.raises(ValueError, match='gzip size does not match'):
        validate_or_raise(result)
