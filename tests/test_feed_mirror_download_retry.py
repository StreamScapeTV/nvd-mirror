from __future__ import annotations

from pathlib import Path

import requests

from app.config import get_settings


class FakeResponse:
    def __init__(self, chunks, headers=None):
        self._chunks = chunks
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        del chunk_size
        for item in self._chunks:
            if isinstance(item, Exception):
                raise item
            yield item

    def close(self):
        return None


def test_stream_failure_retries_entire_download(tmp_path, monkeypatch) -> None:
    import app.feed_mirror as mirror

    monkeypatch.setenv('NVD_UPSTREAM_RETRIES', '2')
    monkeypatch.setenv('NVD_UPSTREAM_RETRY_BACKOFF_SECONDS', '0')
    monkeypatch.setenv('NVD_UPSTREAM_REQUEST_DELAY_SECONDS', '0')
    get_settings.cache_clear()
    responses = iter([
        FakeResponse([b'partial', requests.exceptions.ChunkedEncodingError('broken')]),
        FakeResponse([b'complete'], {'Content-Length': '8'}),
    ])
    monkeypatch.setattr(mirror.requests, 'get', lambda *args, **kwargs: next(responses))
    destination = tmp_path / 'feed.json.gz'

    mirror.download_upstream_feed_file('modified', destination)

    assert destination.read_bytes() == b'complete'
    get_settings.cache_clear()
