from __future__ import annotations

import re
import tomllib
from pathlib import Path


def _match(path: str, pattern: str) -> str:
    content = Path(path).read_text(encoding='utf-8')
    match = re.search(pattern, content, re.MULTILINE)
    assert match is not None, f'Unable to read release version from {path}'
    return match.group(1)


def test_release_versions_are_aligned() -> None:
    versions = {
        'application': _match('app/version.py', r'^__version__\s*=\s*["\']([^"\']+)["\']$'),
        'pyproject': tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'],
        'chart': _match('charts/nvd-mirror/Chart.yaml', r'^version:\s*["\']?([^\s"\']+)["\']?$'),
        'chart appVersion': _match('charts/nvd-mirror/Chart.yaml', r'^appVersion:\s*["\']?([^\s"\']+)["\']?$'),
        'Compose image': _match('.env.example', r'^NVD_MIRROR_IMAGE=.*:([^\s]+)$'),
        'Dockerfile': _match('Dockerfile', r'^ARG APP_VERSION=([^\s]+)$'),
        'Makefile': _match('Makefile', r'^VERSION \?= ([^\s]+)$'),
    }
    assert len(set(versions.values())) == 1, versions
    assert next(iter(versions.values())) == '0.2.0'
