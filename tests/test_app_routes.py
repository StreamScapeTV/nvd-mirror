from __future__ import annotations

import gzip
import importlib
import json
import os
import sys
from pathlib import Path

os.environ.setdefault('DATABASE_URL', 'sqlite:////tmp/nvd-app-routes.sqlite3')
os.environ.setdefault('NVD_FEED_MIRROR_DIR', '/tmp/nvd-app-routes-mirror')

from fastapi.testclient import TestClient


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path / "routes.sqlite3"}')
    monkeypatch.setenv('NVD_FEED_MIRROR_DIR', str(tmp_path / 'mirror'))
    for module_name in ('app.main','app.dashboard','app.dashboard_core','app.models','app.db','app.config','app.feed_mirror'):
        sys.modules.pop(module_name, None)
    import app.config as config_module
    config_module.get_settings.cache_clear()
    main_module = importlib.import_module('app.main')
    return TestClient(main_module.app)


def test_openapi_has_no_admin_routes(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    paths = client.get('/openapi.json').json()['paths']
    assert not any(path.startswith('/admin') for path in paths)
    assert '/rest/json/cves/2.0' in paths
    assert '/mirror/nvd/{filename}' in paths
    assert '/dashboard' not in paths


def test_mirror_route_serves_only_allowed_local_files(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    mirror = tmp_path / 'mirror'; mirror.mkdir(parents=True, exist_ok=True)
    meta = 'lastModifiedDate:2026-06-30T00:00:00-04:00\nsize:2\nzipSize:22\ngzSize:22\nsha256:ABC\n'
    (mirror/'nvdcve-2.0-modified.meta').write_text(meta, encoding='utf-8')
    with gzip.open(mirror/'nvdcve-2.0-modified.json.gz','wb') as fh: fh.write(b'{}')
    response = client.get('/mirror/nvd/nvdcve-2.0-modified.meta')
    assert response.status_code == 200
    assert 'lastModifiedDate:' in response.text
    response = client.get('/mirror/nvd/nvdcve-2.0-modified.json.gz')
    assert response.status_code == 200
    assert gzip.decompress(response.content) == b'{}'
    assert client.get('/mirror/nvd/../../etc/passwd').status_code == 404
    assert client.get('/mirror/nvd/not-an-nvd-file.txt').status_code == 404


def test_dashboard_and_api_return_empty_valid_state(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    page = client.get('/dashboard')
    assert page.status_code == 200
    assert 'NVD Mirror Dashboard' in page.text
    summary = client.get('/dashboard/api/summary')
    assert summary.status_code == 200
    assert summary.json()['database']['totalVulnerabilities'] == 0
    years = client.get('/dashboard/api/years')
    assert years.status_code == 200 and years.json()['years']
    recent = client.get('/dashboard/api/recent?limit=5')
    assert recent.status_code == 200 and recent.json()['items'] == []
    feeds = client.get('/dashboard/api/feeds')
    assert feeds.status_code == 200 and feeds.json()['feeds'][0]['feed'] == 'modified'
