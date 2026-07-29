from __future__ import annotations

import argparse
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import requests

from app.config import get_settings
from app.nvd_feed import (
    FeedValidationResult,
    MetaInfo,
    feed_json_name,
    feed_meta_name,
    inspect_feed_file,
    normalize_feed,
    validate_or_raise,
)

ProgressCallback = Callable[[str], None]

_rate_lock = threading.Lock()
_last_upstream_request_at = 0.0


@dataclass(frozen=True)
class MirroredFeed:
    feed: str
    status: str
    json_path: Path
    meta_path: Path
    meta: MetaInfo
    validation: FeedValidationResult

    def as_dict(self) -> dict[str, object]:
        return {
            'feed': self.feed,
            'status': self.status,
            'jsonPath': str(self.json_path),
            'metaPath': str(self.meta_path),
            'meta': self.meta.as_dict(),
            'validation': self.validation.as_dict(),
        }


class UpstreamDownloadError(RuntimeError):
    pass


def upstream_base_url() -> str:
    settings = get_settings()
    base = settings.nvd_feed_upstream_base_url or settings.nvd_mirror_base_url
    return base.rstrip('/')


def mirror_dir() -> Path:
    path = Path(get_settings().nvd_feed_mirror_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def local_json_path(feed: str) -> Path:
    return mirror_dir() / feed_json_name(feed)


def local_meta_path(feed: str) -> Path:
    return mirror_dir() / feed_meta_name(feed)


def read_local_meta(feed: str) -> MetaInfo:
    path = local_meta_path(feed)
    return MetaInfo.from_text(path.read_text(encoding='utf-8'))


def _requests_verify() -> bool | str:
    settings = get_settings()
    if settings.upstream_ca_bundle:
        return settings.upstream_ca_bundle
    return settings.upstream_verify_tls


def _user_agent() -> str:
    settings = get_settings()
    return settings.nvd_user_agent or f'{settings.app_name}/{settings.app_version}'


def _sleep_before_upstream_request(progress: ProgressCallback | None = None) -> None:
    global _last_upstream_request_at
    delay = float(get_settings().nvd_upstream_request_delay_seconds or 0)
    if delay <= 0:
        return
    with _rate_lock:
        now = time.monotonic()
        elapsed = now - _last_upstream_request_at
        sleep_for = max(0.0, delay - elapsed) if _last_upstream_request_at else 0.0
        if sleep_for > 0:
            if progress is not None:
                progress(f'waiting {sleep_for:.1f}s before next upstream request')
            time.sleep(sleep_for)
        _last_upstream_request_at = time.monotonic()


def _request_with_retries(url: str, *, stream: bool, progress: ProgressCallback | None = None) -> requests.Response:
    settings = get_settings()
    attempts = max(1, int(settings.nvd_upstream_retries))
    backoff = max(0.0, float(settings.nvd_upstream_retry_backoff_seconds))
    last_error: Exception | None = None
    headers = {'User-Agent': _user_agent()}

    for attempt in range(1, attempts + 1):
        _sleep_before_upstream_request(progress)
        try:
            response = requests.get(url, timeout=settings.request_timeout_seconds, verify=_requests_verify(), stream=stream, headers=headers)
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= attempts:
                break
            if progress is not None:
                progress(f'upstream request failed for {url!r} on attempt {attempt}/{attempts}: {exc}')
            if backoff > 0:
                time.sleep(backoff * attempt)

    raise UpstreamDownloadError(f'failed to download {url!r} after {attempts} attempt(s): {last_error}')


def download_upstream_meta_text(feed: str, progress: ProgressCallback | None = None) -> str:
    feed = normalize_feed(feed)
    url = f'{upstream_base_url()}/{feed_meta_name(feed)}'
    if progress is not None:
        progress(f'feed {feed}: fetching upstream meta {url}')
    response = _request_with_retries(url, stream=False, progress=progress)
    return response.text


def download_upstream_feed_file(feed: str, destination: Path, progress: ProgressCallback | None = None) -> None:
    feed = normalize_feed(feed)
    url = f'{upstream_base_url()}/{feed_json_name(feed)}'
    settings = get_settings()
    attempts = max(1, int(settings.nvd_upstream_retries))
    backoff = max(0.0, float(settings.nvd_upstream_retry_backoff_seconds))
    headers = {'User-Agent': _user_agent()}
    report_interval_bytes = int(settings.nvd_download_progress_interval_bytes)
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        downloaded_bytes = 0
        last_reported_bytes = 0
        expected_length: int | None = None
        destination.unlink(missing_ok=True)
        try:
            _sleep_before_upstream_request(progress)
            if progress is not None:
                progress(f'feed {feed}: downloading upstream feed {url} (attempt {attempt}/{attempts})')
            response = requests.get(url, timeout=settings.request_timeout_seconds, verify=_requests_verify(), stream=True, headers=headers)
            try:
                response.raise_for_status()
                content_length = getattr(response, 'headers', {}).get('Content-Length')
                if content_length and content_length.isdigit():
                    expected_length = int(content_length)
                with destination.open('wb') as fh:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        downloaded_bytes += len(chunk)
                        if progress is not None and report_interval_bytes > 0 and downloaded_bytes - last_reported_bytes >= report_interval_bytes:
                            progress(f'feed {feed}: downloaded {downloaded_bytes // (1024 * 1024)} MiB')
                            last_reported_bytes = downloaded_bytes
                if expected_length is not None and downloaded_bytes != expected_length:
                    raise UpstreamDownloadError(f'feed {feed}: incomplete download: got {downloaded_bytes} bytes, expected {expected_length} bytes')
                if progress is not None:
                    progress(f'feed {feed}: download complete ({downloaded_bytes} bytes)')
                return
            finally:
                response.close()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            destination.unlink(missing_ok=True)
            if attempt >= attempts:
                break
            if progress is not None:
                progress(f'feed {feed}: download attempt {attempt}/{attempts} failed: {exc}; retrying in {backoff * attempt:.1f}s')
            if backoff > 0:
                time.sleep(backoff * attempt)

    raise UpstreamDownloadError(f'feed {feed}: failed to download {url!r} after {attempts} attempt(s): {last_error}')


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as fh:
        tmp_name = fh.name
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_name, path)


def _replace_file_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, destination)


def _local_file_is_valid(feed: str, meta: MetaInfo, progress: ProgressCallback | None = None) -> FeedValidationResult | None:
    json_path = local_json_path(feed)
    if not json_path.exists():
        return None
    try:
        result = inspect_feed_file(feed, json_path, meta)
        validate_or_raise(result)
        return result
    except Exception as exc:  # noqa: BLE001
        if progress is not None:
            progress(f'feed {feed}: existing local mirror file is invalid: {exc}')
        return None


def mirror_feed(feed: str, *, force: bool = False, progress: ProgressCallback | None = None) -> MirroredFeed:
    feed = normalize_feed(feed)
    json_path = local_json_path(feed)
    meta_path = local_meta_path(feed)
    settings = get_settings()
    attempts = max(1, int(settings.nvd_upstream_retries))
    backoff = max(0.0, float(settings.nvd_upstream_retry_backoff_seconds))
    last_error: Exception | None = None
    local_meta_for_fallback: MetaInfo | None = None
    local_validation_for_fallback: FeedValidationResult | None = None

    if meta_path.exists() and json_path.exists():
        try:
            local_meta_for_fallback = MetaInfo.from_text(meta_path.read_text(encoding='utf-8'))
            local_validation_for_fallback = _local_file_is_valid(feed, local_meta_for_fallback, progress=progress)
        except Exception as exc:  # noqa: BLE001
            if progress is not None:
                progress(f'feed {feed}: existing local mirror metadata is invalid: {exc}')

    for mirror_attempt in range(1, attempts + 1):
        upstream_meta_text = download_upstream_meta_text(feed, progress=progress)
        upstream_meta = MetaInfo.from_text(upstream_meta_text)
        if not force and local_validation_for_fallback is not None and local_meta_for_fallback is not None:
            local_meta_text = meta_path.read_text(encoding='utf-8')
            if local_meta_text.strip() == upstream_meta_text.strip():
                if progress is not None:
                    progress(f'feed {feed}: local mirror is unchanged and valid')
                return MirroredFeed(feed, 'unchanged', json_path, meta_path, upstream_meta, local_validation_for_fallback)

        with tempfile.NamedTemporaryFile('wb', dir=mirror_dir(), prefix=f'.{feed_json_name(feed)}.', suffix='.tmp', delete=False) as fh:
            tmp_json = Path(fh.name)
        try:
            download_upstream_feed_file(feed, tmp_json, progress=progress)
            validation = inspect_feed_file(feed, tmp_json, upstream_meta)
            validate_or_raise(validation)
            _replace_file_atomic(tmp_json, json_path)
            _write_text_atomic(meta_path, upstream_meta_text)
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            tmp_json.unlink(missing_ok=True)
            if mirror_attempt >= attempts:
                if local_validation_for_fallback is not None and local_meta_for_fallback is not None:
                    if progress is not None:
                        progress(f'feed {feed}: upstream validation failed; keeping existing valid local mirror: {exc}')
                    return MirroredFeed(feed, 'kept-existing-upstream-invalid', json_path, meta_path, local_meta_for_fallback, local_validation_for_fallback)
                raise
            if progress is not None:
                progress(f'feed {feed}: upstream feed did not validate on attempt {mirror_attempt}/{attempts}: {exc}; retrying in {backoff * mirror_attempt:.1f}s')
            if backoff > 0:
                time.sleep(backoff * mirror_attempt)
    else:
        raise UpstreamDownloadError(f'feed {feed}: failed to refresh local mirror: {last_error}')

    if progress is not None:
        progress(f'feed {feed}: local mirror refreshed')
    return MirroredFeed(feed, 'updated', json_path, meta_path, upstream_meta, validation)


def ensure_local_feed(feed: str, *, force: bool = False, progress: ProgressCallback | None = None) -> MirroredFeed:
    settings = get_settings()
    mode = settings.nvd_feed_source_mode.lower().strip()
    feed = normalize_feed(feed)
    if mode == 'managed':
        return mirror_feed(feed, force=force, progress=progress)
    if mode == 'local':
        meta = read_local_meta(feed)
        path = local_json_path(feed)
        validation = inspect_feed_file(feed, path, meta)
        validate_or_raise(validation)
        return MirroredFeed(feed, 'local', path, local_meta_path(feed), meta, validation)
    if mode == 'remote':
        return mirror_feed(feed, force=force, progress=progress)
    raise ValueError(f'Unsupported NVD_FEED_SOURCE_MODE: {settings.nvd_feed_source_mode}')


def iter_year_feeds(from_year: int, to_year: int) -> Iterable[str]:
    if from_year > to_year:
        raise ValueError('from_year must be <= to_year')
    for year in range(from_year, to_year + 1):
        yield str(year)


def mirror_feeds(feeds: Iterable[str], *, force: bool = False, progress: ProgressCallback | None = None) -> list[MirroredFeed]:
    return [mirror_feed(feed, force=force, progress=progress) for feed in feeds]


def _emit_progress(message: str) -> None:
    print(f'[mirror] {message}', flush=True)


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description='Synchronize raw NVD feed files into the local mirror directory.')
    parser.add_argument('mode', choices=['modified', 'recent', 'year', 'all'])
    parser.add_argument('--year', type=int)
    parser.add_argument('--from-year', type=int, default=settings.default_from_year)
    parser.add_argument('--to-year', type=int, default=time.gmtime().tm_year)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    if args.mode == 'modified':
        feeds = ['modified']
    elif args.mode == 'recent':
        feeds = ['recent']
    elif args.mode == 'year':
        if args.year is None:
            raise SystemExit('--year is required when mode=year')
        feeds = [str(args.year)]
    else:
        feeds = list(iter_year_feeds(args.from_year, args.to_year)) + ['modified', 'recent']
    for result in mirror_feeds(feeds, force=args.force, progress=_emit_progress):
        print(result.as_dict())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
