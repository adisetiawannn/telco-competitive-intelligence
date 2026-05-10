"""
Migration 004 — create table competitor_mentions
Relasi many-to-many antara artikel dan kompetitor.
Sentiment spesifik per kompetitor per artikel.
"""

import sqlite3
import logging

logger = logging.getLogger(__name__)

MIGRATION_ID = "m004"
DESCRIPTION  = "create competitor_mentions table"


def up(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()

    cursor.execute("PRAGMA foreign_keys = ON")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS competitor_mentions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id      INTEGER NOT NULL,
            competitor      TEXT NOT NULL,
            mention_count   INTEGER DEFAULT 1,
            sentiment_score REAL,
            FOREIGN KEY (article_id)
                REFERENCES articles(id)
                ON DELETE CASCADE,
            UNIQUE(article_id, competitor)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_mentions_competitor
        ON competitor_mentions(competitor)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_mentions_article_competitor
        ON competitor_mentions(article_id, competitor)
    """)

    conn.commit()
    logger.info(f"[{MIGRATION_ID}] selesai — {DESCRIPTION}")


def down(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS competitor_mentions")
    conn.commit()
    logger.info(f"[{MIGRATION_ID}] rolled back — table dihapus")