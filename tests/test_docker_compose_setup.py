from __future__ import annotations

from pathlib import Path


def test_dockerfile_uses_cmd_so_compose_services_can_override_command() -> None:
    dockerfile = Path('Dockerfile').read_text(encoding='utf-8')
    assert 'CMD ["/app/scripts/start.sh"]' in dockerfile
    assert 'ENTRYPOINT ["/app/scripts/start.sh"]' not in dockerfile


def test_dockerfile_does_not_force_specific_runtime_user() -> None:
    dockerfile = Path('Dockerfile').read_text(encoding='utf-8')
    assert 'USER appuser' not in dockerfile
    assert 'useradd --create-home --uid 10001 appuser' not in dockerfile


def test_compose_uses_env_file_as_single_runtime_entrypoint() -> None:
    compose = Path('docker-compose.yml').read_text(encoding='utf-8')
    assert 'env_file:' in compose and '- .env' in compose
    assert 'DATABASE_URL: ${DATABASE_URL' not in compose
    assert 'NVD_MIRROR_BASE_URL: ${NVD_MIRROR_BASE_URL' not in compose


def test_deployment_compose_pulls_the_published_image_without_building_source() -> None:
    compose = Path('docker-compose.yml').read_text(encoding='utf-8')
    assert 'image: ${NVD_MIRROR_IMAGE}' in compose
    assert 'pull_policy: ${NVD_MIRROR_PULL_POLICY:-missing}' in compose
    assert 'build:' not in compose


def test_contributor_compose_override_builds_runtime_and_test_images() -> None:
    compose = Path('docker-compose.dev.yml').read_text(encoding='utf-8')
    assert 'target: runtime' in compose
    assert 'target: test' in compose
    assert 'image: nvd-mirror:local' in compose
    assert 'image: nvd-mirror:test' in compose


def test_compose_has_persistent_local_bind_mounts() -> None:
    compose = Path('docker-compose.yml').read_text(encoding='utf-8')
    assert './volumes/database:/var/lib/postgresql/data' in compose
    assert './volumes/nvd-feed-mirror-data:${NVD_FEED_MIRROR_DIR}' in compose
    assert './volumes/certs:/certs:ro' in compose


def test_compose_has_scheduler_service_and_no_external_scheduler_dependency() -> None:
    compose = Path('docker-compose.yml').read_text(encoding='utf-8')
    assert 'scheduler:' in compose
    assert '["python", "-m", "app.scheduler"]' in compose
    assert 'CronJob' not in compose


def test_compose_has_manual_bootstrap_and_sync_profiles() -> None:
    compose = Path('docker-compose.yml').read_text(encoding='utf-8')
    assert 'bootstrap:' in compose and '["python", "-m", "app.sync", "bootstrap"]' in compose
    assert 'sync-modified:' in compose and '["python", "-m", "app.sync", "modified"]' in compose
    assert 'mirror-all:' in compose and '["python", "-m", "app.feed_mirror", "all"]' in compose
    assert 'stats-backfill:' in compose
    assert '["python", "-m", "app.nvd_stats", "backfill-missing", "--batch-size", "1000"]' in compose
    assert 'profiles: ["manual"]' in compose


def test_env_example_contains_single_entrypoint_variables_for_compose() -> None:
    env = Path('.env.example').read_text(encoding='utf-8')
    for name in [
        'API_HOST_PORT',
        'POSTGRES_HOST_PORT',
        'NVD_MIRROR_IMAGE',
        'NVD_MIRROR_PULL_POLICY',
        'NVD_MIRROR_BASE_URL',
        'NVD_FEED_SOURCE_MODE',
        'NVD_FEED_MIRROR_DIR',
        'NVD_UPSTREAM_REQUEST_DELAY_SECONDS',
        'NVD_SYNC_TIMEZONE',
        'NVD_SYNC_MODIFIED_EVERY_HOURS',
        'NVD_SYNC_MODIFIED_MINUTE',
        'NVD_SYNC_DAILY_MIRROR_HOUR',
        'NVD_SYNC_DAILY_MIRROR_MINUTE',
        'DATABASE_URL',
        'POSTGRES_PASSWORD',
    ]:
        assert f'{name}=' in env
    assert 'NVD_MIRROR_IMAGE=ghcr.io/streamscapetv/nvd-mirror:0.2.0' in env
