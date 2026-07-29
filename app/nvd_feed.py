from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CveRecord, FeedImport, utcnow
from app.nvd_stats import derive_cve_stats_row, upsert_cve_stats_batch
from app.utils import cve_year, parse_dt

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class MetaInfo:
    last_modified_date: str | None
    size: int | None
    zip_size: int | None
    gz_size: int | None
    sha256: str | None

    @classmethod
    def from_text(cls, text: str) -> 'MetaInfo':
        values: dict[str, str] = {}
        for line in text.splitlines():
            if ':' not in line:
                continue
            key, value = line.split(':', 1)
            values[key.strip()] = value.strip()

        def as_int(name: str) -> int | None:
            raw = values.get(name)
            return int(raw) if raw and raw.isdigit() else None

        return cls(
            last_modified_date=values.get('lastModifiedDate'),
            size=as_int('size'),
            zip_size=as_int('zipSize'),
            gz_size=as_int('gzSize'),
            sha256=(values.get('sha256') or '').upper() or None,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            'lastModifiedDate': self.last_modified_date,
            'size': self.size,
            'zipSize': self.zip_size,
            'gzSize': self.gz_size,
            'sha256': self.sha256,
        }


@dataclass(frozen=True)
class FeedValidationResult:
    feed: str
    gzip_bytes: int
    uncompressed_bytes: int
    uncompressed_sha256: str
    gzip_size_matches_meta: bool | None
    uncompressed_size_matches_meta: bool | None
    uncompressed_sha256_matches_meta: bool | None
    gzip_ok: bool
    format: str | None
    version: str | None
    total_results: int | None
    array_length: int | None
    timestamp: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            'feed': self.feed,
            'gzipBytes': self.gzip_bytes,
            'uncompressedBytes': self.uncompressed_bytes,
            'uncompressedSha256': self.uncompressed_sha256,
            'gzipSizeMatchesMeta': self.gzip_size_matches_meta,
            'uncompressedSizeMatchesMeta': self.uncompressed_size_matches_meta,
            'uncompressedSha256MatchesMeta': self.uncompressed_sha256_matches_meta,
            'gzipOk': self.gzip_ok,
            'format': self.format,
            'version': self.version,
            'totalResults': self.total_results,
            'arrayLength': self.array_length,
            'timestamp': self.timestamp,
        }


def normalize_feed(feed: str) -> str:
    feed = str(feed).strip().lower()
    if feed in {'modified', 'recent'}:
        return feed
    if feed.isdigit() and 1900 <= int(feed) <= 9999:
        return feed
    raise ValueError(f'Invalid feed name: {feed}')


def feed_json_name(feed: str) -> str:
    return f'nvdcve-2.0-{normalize_feed(feed)}.json.gz'


def feed_meta_name(feed: str) -> str:
    return f'nvdcve-2.0-{normalize_feed(feed)}.meta'


def _base_url() -> str:
    settings = get_settings()
    return (settings.nvd_feed_upstream_base_url or settings.nvd_mirror_base_url).rstrip('/')


def _requests_verify() -> bool | str:
    settings = get_settings()
    if settings.upstream_ca_bundle:
        return settings.upstream_ca_bundle
    return settings.upstream_verify_tls


def download_meta(feed: str) -> MetaInfo:
    settings = get_settings()
    url = f'{_base_url()}/{feed_meta_name(feed)}'
    response = requests.get(url, timeout=settings.request_timeout_seconds, verify=_requests_verify())
    response.raise_for_status()
    return MetaInfo.from_text(response.text)


def download_feed_file(feed: str, progress: ProgressCallback | None = None) -> Path:
    settings = get_settings()
    url = f'{_base_url()}/{feed_json_name(feed)}'
    tmp_dir = Path(tempfile.mkdtemp(prefix='nvd-feed-'))
    out = tmp_dir / feed_json_name(feed)
    downloaded_bytes = 0
    last_reported_bytes = 0
    report_interval_bytes = 50 * 1024 * 1024

    with requests.get(url, timeout=settings.request_timeout_seconds, stream=True, verify=_requests_verify()) as response:
        response.raise_for_status()
        if progress is not None:
            progress(f'feed {feed}: downloading {url}')
        with out.open('wb') as fh:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)
                    downloaded_bytes += len(chunk)
                    if progress is not None and downloaded_bytes - last_reported_bytes >= report_interval_bytes:
                        progress(f'feed {feed}: downloaded {downloaded_bytes // (1024 * 1024)} MiB')
                        last_reported_bytes = downloaded_bytes

    if progress is not None:
        progress(f'feed {feed}: download complete ({downloaded_bytes // (1024 * 1024)} MiB)')
    return out


def inspect_feed_file(feed: str, gz_path: Path, meta: MetaInfo | None = None) -> FeedValidationResult:
    gzip_bytes = os.path.getsize(gz_path)
    hasher = hashlib.sha256()
    uncompressed_bytes = 0
    gzip_ok = True
    payload: dict[str, Any] | None = None

    try:
        with gzip.open(gz_path, 'rb') as fh:
            raw = fh.read()
        uncompressed_bytes = len(raw)
        hasher.update(raw)
        payload = json.loads(raw.decode('utf-8'))
    except Exception:
        gzip_ok = False
        raise

    uncompressed_sha = hasher.hexdigest().upper()
    vulnerabilities = payload.get('vulnerabilities') if payload else None

    gzip_size_matches_meta = None
    uncompressed_size_matches_meta = None
    sha_matches_meta = None
    if meta:
        if meta.gz_size is not None:
            gzip_size_matches_meta = gzip_bytes == meta.gz_size
        if meta.size is not None:
            uncompressed_size_matches_meta = uncompressed_bytes == meta.size
        if meta.sha256:
            sha_matches_meta = uncompressed_sha == meta.sha256.upper()

    return FeedValidationResult(
        feed=normalize_feed(feed),
        gzip_bytes=gzip_bytes,
        uncompressed_bytes=uncompressed_bytes,
        uncompressed_sha256=uncompressed_sha,
        gzip_size_matches_meta=gzip_size_matches_meta,
        uncompressed_size_matches_meta=uncompressed_size_matches_meta,
        uncompressed_sha256_matches_meta=sha_matches_meta,
        gzip_ok=gzip_ok,
        format=payload.get('format') if payload else None,
        version=payload.get('version') if payload else None,
        total_results=payload.get('totalResults') if payload else None,
        array_length=len(vulnerabilities) if isinstance(vulnerabilities, list) else None,
        timestamp=payload.get('timestamp') if payload else None,
    )


def validate_or_raise(result: FeedValidationResult) -> None:
    settings = get_settings()
    failures: list[str] = []
    meta_validation_enabled = settings.validate_meta

    if not result.gzip_ok:
        failures.append('gzip validation failed')
    if meta_validation_enabled and settings.validate_gz_size and result.gzip_size_matches_meta is False:
        failures.append('gzip size does not match meta gzSize')
    if meta_validation_enabled and settings.validate_uncompressed_size and result.uncompressed_size_matches_meta is False:
        failures.append('uncompressed size does not match meta size')
    if meta_validation_enabled and settings.validate_uncompressed_sha256 and result.uncompressed_sha256_matches_meta is False:
        failures.append('uncompressed SHA256 does not match meta sha256')
    if result.total_results is not None and result.array_length is not None and result.total_results != result.array_length:
        failures.append(f'totalResults ({result.total_results}) does not equal vulnerabilities length ({result.array_length})')
    if failures:
        raise ValueError('; '.join(failures))


def inspect_remote_feed(feed: str) -> dict[str, Any]:
    meta = download_meta(feed)
    path = download_feed_file(feed)
    result = inspect_feed_file(feed, path, meta)
    return {'meta': meta.as_dict(), 'validation': result.as_dict()}


def _upsert_cve_batch(db: Session, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    dialect = db.bind.dialect.name if db.bind is not None else ''
    update_columns = {
        'year': None,
        'published': None,
        'last_modified': None,
        'source_feed': None,
        'raw_json': None,
        'imported_at': None,
    }

    if dialect == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
        stmt = insert(CveRecord).values(rows)
        excluded = stmt.excluded
        stmt = stmt.on_conflict_do_update(index_elements=[CveRecord.cve_id], set_={key: getattr(excluded, key) for key in update_columns})
        db.execute(stmt)
        return

    if dialect == 'sqlite':
        from sqlalchemy.dialects.sqlite import insert
        stmt = insert(CveRecord).values(rows)
        excluded = stmt.excluded
        stmt = stmt.on_conflict_do_update(index_elements=[CveRecord.cve_id], set_={key: getattr(excluded, key) for key in update_columns})
        db.execute(stmt)
        return

    for row in rows:
        db.merge(CveRecord(**row))


def _prepare_feed_for_import(feed: str, progress: ProgressCallback | None = None) -> tuple[MetaInfo, Path, FeedValidationResult, dict[str, Any]]:
    settings = get_settings()
    mode = settings.nvd_feed_source_mode.lower().strip()
    if mode in {'managed', 'local'}:
        from app.feed_mirror import ensure_local_feed
        mirrored = ensure_local_feed(feed, progress=progress)
        return mirrored.meta, mirrored.json_path, mirrored.validation, mirrored.as_dict()
    if mode == 'remote':
        meta = download_meta(feed)
        path = download_feed_file(feed, progress=progress)
        result = inspect_feed_file(feed, path, meta)
        validate_or_raise(result)
        return meta, path, result, {'feed': feed, 'status': 'remote', 'jsonPath': str(path), 'meta': meta.as_dict(), 'validation': result.as_dict()}
    raise ValueError(f'Unsupported NVD_FEED_SOURCE_MODE: {settings.nvd_feed_source_mode}')


def import_feed(feed: str, db: Session, progress: ProgressCallback | None = None) -> dict[str, Any]:
    feed = normalize_feed(feed)
    meta, path, result, source = _prepare_feed_for_import(feed, progress=progress)
    if progress is not None:
        progress(f'feed {feed}: validation passed')
    with gzip.open(path, 'rt', encoding='utf-8') as fh:
        payload = json.load(fh)
    vulnerabilities = payload.get('vulnerabilities') or []
    if progress is not None:
        progress(f'feed {feed}: importing {len(vulnerabilities)} vulnerabilities')
    imported = 0
    batch: list[dict[str, Any]] = []
    stats_batch: list[dict[str, Any]] = []
    batch_size = 1000
    progress_interval = 5000

    for item in vulnerabilities:
        cve = item.get('cve') or {}
        cve_id = cve.get('id')
        if not cve_id:
            continue
        batch.append({
            'cve_id': cve_id,
            'year': cve_year(cve_id),
            'published': parse_dt(cve.get('published')),
            'last_modified': parse_dt(cve.get('lastModified')),
            'source_feed': feed,
            'raw_json': json.dumps(item, ensure_ascii=False, separators=(',', ':')),
            'imported_at': utcnow(),
        })
        stats_row = derive_cve_stats_row(item)
        if stats_row:
            stats_batch.append(stats_row)
        imported += 1
        if len(batch) >= batch_size:
            _upsert_cve_batch(db, batch)
            upsert_cve_stats_batch(db, stats_batch)
            db.commit()
            batch.clear()
            stats_batch.clear()
            if progress is not None and imported % progress_interval == 0:
                progress(f'feed {feed}: committed {imported}/{len(vulnerabilities)} vulnerabilities')

    if batch:
        _upsert_cve_batch(db, batch)
        upsert_cve_stats_batch(db, stats_batch)
        db.commit()
        if progress is not None:
            progress(f'feed {feed}: committed {imported}/{len(vulnerabilities)} vulnerabilities')

    feed_import = FeedImport(
        feed=feed,
        last_modified_date=meta.last_modified_date,
        size=meta.size,
        gz_size=meta.gz_size,
        sha256=meta.sha256,
        status='ok',
        records_imported=imported,
        error=None,
        imported_at=utcnow(),
    )
    db.merge(feed_import)
    db.commit()
    if progress is not None:
        progress(f'feed {feed}: completed import ({imported} records)')
    return {'feed': feed, 'recordsImported': imported, 'meta': meta.as_dict(), 'validation': result.as_dict(), 'source': source}
