"""
Migration 001 — alter table articles
Tambahkan kolom tracking untuk content fetch dan NLP processing.
"""

import sqlite3
import logging

logger = logging.getLogger(__name__)

MIGRATION_ID = "m001"
DESCRIPTION = "add processing status columns to articles table"

def up(conn: sqlite3.Connection) -> None:
    """apply migration - tambah kolom baru ke articles table"""
    cursor = conn.cursor()

    # TAMBAH KOLOM BARU DISINI !
    new_columns = [
        ("content_fetched", "INTEGER DEFAULT 0"),
        ("nlp_processed", "INTEGER DEFAULT 0"),
        ("processing_error", "TEXT"),
        ("fetch_attempts", "INTEGER DEFAULT 0"),
    ]

    existing = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(articles)")
    }

    for col_name, col_def in new_columns:
        if col_name not in existing:
            cursor.execute(
                f"ALTER TABLE articles ADD COLUMN {col_name} {col_def}"
            )
            logger.info(f"  + kolom '{col_name}' ditambahkan")
        else:
            logger.info(f"  ~ kolom '{col_name}' sudah ada, skip")
        

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_articles_published
        ON articles(published)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_articles_content_fetched
        ON articles(content_fetched)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_articles_nlp_processed
        ON articles(nlp_processed)
    """)

    conn.commit()
    logger.info(f"[{MIGRATION_ID}] selesai — {DESCRIPTION}")


def down(conn: sqlite3.Connection) -> None:
    """
    Rollback — SQLite tidak support DROP COLUMN sebelum v3.35.
    Alternatifnya: recreate table. Untuk sekarang log warning saja.
    """
    logger.warning(
        f"[{MIGRATION_ID}] rollback tidak tersedia untuk ALTER TABLE "
        f"di SQLite — restore dari backup jika diperlukan."
    )