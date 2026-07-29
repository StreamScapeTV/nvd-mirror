from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import create_tables, session_scope
from app.models import CveRecord, FeedImport
from app.nvd_feed import import_feed
from app.nvd_stats import refresh_nvd_stats_snapshot

ProgressCallback = Callable[[str], None]


def plan_sync_feeds(mode: str, from_year: int, to_year: int, has_existing_data: bool) -> list[str]:
    if from_year > to_year:
        raise ValueError('from_year must be <= to_year')
    if mode == 'modified':
        return ['modified']
    feeds = [str(year) for year in range(from_year, to_year + 1)]
    if mode == 'backfill':
        return feeds
    if mode in {'all', 'bootstrap'}:
        return feeds + ['modified']
    raise ValueError(f'Unsupported sync mode: {mode}')


def has_existing_cves(db: Session) -> bool:
    return bool(db.execute(select(func.count()).select_from(CveRecord)).scalar_one())


def _emit_progress(message: str) -> None:
    print(f'[sync] {datetime.now(timezone.utc).isoformat(timespec="seconds")}Z {message}', flush=True)


def run_sync(mode: str, from_year: int, to_year: int) -> dict[str, object]:
    create_tables()
    with session_scope() as db:
        feeds = plan_sync_feeds(mode, from_year, to_year, has_existing_cves(db))
        _emit_progress(f'planned feeds ({len(feeds)}): {", ".join(feeds)}')
        results = []
        for index, feed in enumerate(feeds, start=1):
            _emit_progress(f'starting feed {index}/{len(feeds)}: {feed}')
            result = import_feed(feed, db, progress=_emit_progress)
            results.append(result)
            _emit_progress(f'completed feed {index}/{len(feeds)}: {feed} ({result["recordsImported"]} records)')
        latest_feed = db.execute(select(FeedImport).order_by(FeedImport.imported_at.desc()).limit(1)).scalar_one_or_none()
        try:
            refresh_nvd_stats_snapshot(db, progress=_emit_progress)
        except Exception as exc:  # noqa: BLE001
            _emit_progress(f'dashboard stats snapshot refresh failed: {exc!r}')
    return {
        'mode': mode,
        'feedsImported': len(results),
        'feeds': feeds,
        'lastFeedImported': latest_feed.feed if latest_feed else None,
        'results': results,
    }


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(description='Synchronize NVD mirror feeds into the local database.')
    parser.add_argument('mode', choices=['bootstrap', 'all', 'backfill', 'modified'])
    parser.add_argument('--from-year', type=int, default=settings.default_from_year)
    parser.add_argument('--to-year', type=int, default=datetime.now(timezone.utc).year)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_sync(mode=args.mode, from_year=args.from_year, to_year=args.to_year)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
