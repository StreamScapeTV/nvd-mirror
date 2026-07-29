from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.version import __version__


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith('postgresql+psycopg://'):
        return database_url
    if database_url.startswith('postgresql://'):
        return database_url.replace('postgresql://', 'postgresql+psycopg://', 1)
    if database_url.startswith('postgres://'):
        return database_url.replace('postgres://', 'postgresql+psycopg://', 1)
    return database_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'nvd-mirror'
    app_version: str = __version__
    database_url: str = Field(
        default='sqlite:////data/nvd-mirror.sqlite3',
        description='SQLAlchemy database URL. Use postgresql+psycopg://user:pass@host:5432/db for Postgres.',
    )
    nvd_mirror_base_url: str = Field(
        default='https://nvd.nist.gov/feeds/json/cve/2.0',
        description=(
            'Upstream NVD JSON 2.0 feed base URL, without trailing slash. '
            'May point to the official NVD feeds or another feed-compatible mirror.'
        ),
    )
    nvd_feed_upstream_base_url: Optional[str] = Field(
        default=None,
        description='Optional explicit upstream feed base URL. Overrides NVD_MIRROR_BASE_URL when set.',
    )
    nvd_feed_source_mode: str = Field(
        default='managed',
        description='managed downloads files into NVD_FEED_MIRROR_DIR first; local reads only local files; remote streams from upstream.',
    )
    nvd_feed_mirror_dir: str = Field(
        default='/data/mirror/nvd',
        description='Directory for locally mirrored nvdcve-2.0-*.meta and nvdcve-2.0-*.json.gz files.',
    )
    nvd_upstream_request_delay_seconds: float = Field(
        default=6.0,
        description='Minimum delay between upstream requests. Use 0 only for a trusted local mirror.',
    )
    nvd_upstream_retries: int = 10
    nvd_upstream_retry_backoff_seconds: float = 15.0
    nvd_download_progress_interval_bytes: int = 52428800
    nvd_user_agent: Optional[str] = None
    nvd_api_key: Optional[str] = Field(
        default=None,
        description='Optional NVD API key used only for lightweight live API total checks.',
    )
    nvd_api_cves_url: str = 'https://services.nvd.nist.gov/rest/json/cves/2.0'
    nvd_api_cpes_url: str = 'https://services.nvd.nist.gov/rest/json/cpes/2.0'
    live_nvd_total_cache_ttl_seconds: int = 300
    dashboard_stats_cache_seconds: int = 600
    request_timeout_seconds: int = 900
    upstream_verify_tls: bool = True
    upstream_ca_bundle: Optional[str] = None
    max_results_per_page: int = 2000
    validate_meta: bool = True
    validate_uncompressed_sha256: bool = True
    validate_uncompressed_size: bool = True
    validate_gz_size: bool = True
    default_from_year: int = 2002
    port: int = 8000
    tls_cert_file: Optional[str] = None
    tls_key_file: Optional[str] = None

    scheduler_enabled: bool = True
    scheduler_run_on_startup: str = Field(
        default='modified',
        description='Optional startup action for scheduler: none, modified, bootstrap, or all.',
    )
    scheduler_max_sleep_seconds: int = 60
    nvd_sync_timezone: str = 'America/New_York'
    nvd_sync_modified_enabled: bool = True
    nvd_sync_modified_every_hours: int = 1
    nvd_sync_modified_minute: int = 25
    nvd_sync_daily_mirror_enabled: bool = True
    nvd_sync_daily_mirror_hour: int = 3
    nvd_sync_daily_mirror_minute: int = 15
    nvd_sync_daily_mirror_force: bool = False

    @field_validator('database_url', mode='before')
    @classmethod
    def normalize_sqlalchemy_database_url(cls, value: str) -> str:
        return normalize_database_url(value)


@lru_cache
def get_settings() -> Settings:
    return Settings()
