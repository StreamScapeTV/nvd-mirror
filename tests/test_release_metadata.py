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
    assert next(iter(versions.values())) == '0.2.1'


def test_package_metadata_has_personal_source_license_and_version() -> None:
    dockerfile = Path('Dockerfile').read_text(encoding='utf-8')
    chart = Path('charts/nvd-mirror/Chart.yaml').read_text(encoding='utf-8')

    assert 'org.opencontainers.image.source="https://github.com/mimranfaruqi/nvd-mirror"' in dockerfile
    assert 'org.opencontainers.image.licenses="MIT"' in dockerfile
    assert 'org.opencontainers.image.version="${APP_VERSION}"' in dockerfile

    assert 'org.opencontainers.image.source: https://github.com/mimranfaruqi/nvd-mirror' in chart
    assert 'org.opencontainers.image.licenses: MIT' in chart
    assert 'org.opencontainers.image.version: "0.2.1"' in chart


def test_current_metadata_does_not_reference_previous_package_owner() -> None:
    old_owner = ''.join(['stream', 'scape', 'tv'])
    old_display_owner = ''.join(['Stream', 'Scape', 'TV'])
    old_references = [
        old_owner,
        f'ghcr.io/{old_owner}',
        f'github.com/{old_display_owner}',
    ]
    scanned_files = [
        Path('.env.example'),
        Path('CONTRIBUTING.md'),
        Path('Dockerfile'),
        Path('Makefile'),
        Path('README.md'),
        Path('SECURITY.md'),
        Path('NOTICE.md'),
        Path('docker-compose.yml'),
        Path('docker-compose.dev.yml'),
        Path('pyproject.toml'),
        Path('.github/PULL_REQUEST_TEMPLATE.md'),
        *Path('.github/workflows').glob('*.yml'),
        *Path('charts/nvd-mirror').glob('*.yaml'),
        Path('charts/nvd-mirror/README.md'),
    ]

    offenders: dict[str, list[str]] = {}
    for path in scanned_files:
        content = path.read_text(encoding='utf-8')
        content_lower = content.lower()
        matches = [
            reference
            for reference in old_references
            if reference.lower() in content_lower
        ]
        if matches:
            offenders[str(path)] = matches

    assert offenders == {}
