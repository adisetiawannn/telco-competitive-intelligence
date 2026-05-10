"""
Migration 005 — create table competitor_daily_stats
Pre-aggregated metrics per kompetitor per hari.
Digunakan untuk dashboard — tidak perlu compute saat query.
"""

import sqlite3
import logging

logger = logging.getLogger(__name__)

MIGRATION_ID = "m005"
DESCRIPTION  = "create competitor_daily_stats table"


def up(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()

    cursor.execute("PRAGMA foreign_keys = ON")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS competitor_daily_stats (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            competitor      TEXT NOT NULL,
            date            TEXT NOT NULL,
            mention_count   INTEGER DEFAULT 0,
            positive_count  INTEGER DEFAULT 0,
            negative_count  INTEGER DEFAULT 0,
            neutral_count   INTEGER DEFAULT 0,
            avg_sentiment   REAL,
            top_topics      TEXT,
            top_sources     TEXT,
            share_of_voice  REAL,
            UNIQUE(competitor, date)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_daily_stats_date
        ON competitor_daily_stats(date)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_daily_stats_competitor_date
        ON competitor_daily_stats(competitor, date)
    """)

    conn.commit()
    logger.info(f"[{MIGRATION_ID}] selesai — {DESCRIPTION}")


def down(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS competitor_daily_stats")
    conn.commit()
    logger.info(f"[{MIGRATION_ID}] rolled back — table dihapus")