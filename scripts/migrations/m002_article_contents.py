"""
Migration 002 — create table article_contents
Simpan full content artikel terpisah dari metadata
untuk query performance.
"""

import sqlite3
import logging

logger = logging.getLogger(__name__)

MIGRATION_ID = "m002"
DESCRIPTION  = "create article_contents table"


def up(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()

    cursor.execute("PRAGMA foreign_keys = ON")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS article_contents (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id     INTEGER NOT NULL UNIQUE,
            full_content   TEXT,
            content_length INTEGER,
            fetched_at     TEXT NOT NULL,
            fetch_error    TEXT,
            FOREIGN KEY (article_id)
                REFERENCES articles(id)
                ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_contents_article_id
        ON article_contents(article_id)
    """)

    conn.commit()
    logger.info(f"[{MIGRATION_ID}] selesai — {DESCRIPTION}")


def down(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS article_contents")
    conn.commit()
    logger.info(f"[{MIGRATION_ID}] rolled back — table dihapus")