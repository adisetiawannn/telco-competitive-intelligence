"""
Migration 006 — add fetch_attempts to articles
Track jumlah retry untuk content fetching.
"""

import sqlite3
import logging

logger = logging.getLogger(__name__)

MIGRATION_ID = "m006"
DESCRIPTION  = "add fetch_attempts column to articles"


def up(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()

    existing = {
        row[1] for row in cursor.execute("PRAGMA table_info(articles)")
    }

    if "fetch_attempts" not in existing:
        cursor.execute(
            "ALTER TABLE articles ADD COLUMN fetch_attempts INTEGER DEFAULT 0"
        )
        logger.info("  + kolom 'fetch_attempts' ditambahkan")
    else:
        logger.info("  ~ kolom 'fetch_attempts' sudah ada, skip")

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_articles_fetch_status
        ON articles(content_fetched, fetch_attempts)
    """)

    conn.commit()
    logger.info(f"[{MIGRATION_ID}] selesai — {DESCRIPTION}")


def down(conn: sqlite3.Connection) -> None:
    logger.warning(
        f"[{MIGRATION_ID}] rollback tidak tersedia untuk ALTER TABLE."
    )