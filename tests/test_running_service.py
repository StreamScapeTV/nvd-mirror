from __future__ import annotations

import os

import httpx
import pytest

API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:8000').rstrip('/')
RUN_INTEGRATION = os.getenv('RUN_INTEGRATION', '0') == '1'


@pytest.mark.skipif(not RUN_INTEGRATION, reason='Set RUN_INTEGRATION=1 to test a running service')
def test_health() -> None:
    response = httpx.get(f'{API_BASE_URL}/health', timeout=10)
    response.raise_for_status()
    assert response.json()['status'] == 'ok'


@pytest.mark.skipif(not RUN_INTEGRATION, reason='Set RUN_INTEGRATION=1 to test a running service')
def test_openapi_has_public_routes_and_no_admin_routes() -> None:
    response = httpx.get(f'{API_BASE_URL}/openapi.json', timeout=30)
    response.raise_for_status()
    paths = response.json()['paths']
    assert '/rest/json/cves/2.0' in paths
    assert '/mirror/nvd/{filename}' in paths
    assert not any(path == '/admin' or path.startswith('/admin/') for path in paths)


@pytest.mark.skipif(not RUN_INTEGRATION, reason='Set RUN_INTEGRATION=1 to test a populated running service')
def test_query_api() -> None:
    response = httpx.get(f'{API_BASE_URL}/rest/json/cves/2.0?resultsPerPage=1', timeout=30)
    response.raise_for_status()
    data = response.json()
    assert data['format'] == 'NVD_CVE'
    assert data['version'] == '2.0'
    assert len(data['vulnerabilities']) <= 1
    if data['totalResults'] > 0:
        assert data['vulnerabilities'][0]['cve']['id'].startswith('CVE-')
