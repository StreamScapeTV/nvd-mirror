from __future__ import annotations

import os

os.environ.setdefault('DATABASE_URL', 'sqlite:////tmp/nvd-sync-planning.sqlite3')

from app.sync import plan_sync_feeds


def test_bootstrap_mode_imports_full_history_when_database_is_empty() -> None:
    assert plan_sync_feeds(mode='bootstrap', from_year=2023, to_year=2025, has_existing_data=False) == ['2023','2024','2025','modified']


def test_bootstrap_mode_imports_full_history_even_when_database_has_partial_data() -> None:
    assert plan_sync_feeds(mode='bootstrap', from_year=2023, to_year=2025, has_existing_data=True) == ['2023','2024','2025','modified']


def test_all_mode_imports_year_range_and_modified_feed() -> None:
    assert plan_sync_feeds(mode='all', from_year=2023, to_year=2025, has_existing_data=True) == ['2023','2024','2025','modified']


def test_backfill_mode_imports_only_year_range() -> None:
    assert plan_sync_feeds(mode='backfill', from_year=2023, to_year=2025, has_existing_data=True) == ['2023','2024','2025']
