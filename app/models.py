from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CveRecord(Base):
    __tablename__ = 'nvd_cves'

    cve_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    year: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)
    published: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    last_modified: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    source_feed: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        Index('ix_nvd_cves_pub_lastmod', 'published', 'last_modified'),
    )


class FeedImport(Base):
    __tablename__ = 'nvd_feed_imports'

    feed: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_modified_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    gz_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default='unknown', nullable=False)
    records_imported: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class DashboardStatsSnapshot(Base):
    __tablename__ = 'nvd_dashboard_stats_snapshots'

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default='ok', nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class CveDerivedStats(Base):
    __tablename__ = 'nvd_cve_derived_stats'

    cve_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    vuln_status: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    source_identifier: Mapped[Optional[str]] = mapped_column(String(256), index=True, nullable=True)
    cvss_v3_severity: Mapped[Optional[str]] = mapped_column(String(32), index=True, nullable=True)
    cvss_v2_severity: Mapped[Optional[str]] = mapped_column(String(32), index=True, nullable=True)
    has_configurations: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_weaknesses: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cpe_match_entries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reference_entries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description_entries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
