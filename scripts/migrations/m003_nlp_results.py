"""
Migration 003 — create table nlp_results
Output NLP per artikel: sentiment, topics, keywords, entities.
"""

import sqlite3
import logging

logger = logging.getLogger(__name__)

MIGRATION_ID = "m003"
DESCRIPTION  = "create nlp_results table"


def up(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()

    cursor.execute("PRAGMA foreign_keys = ON")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nlp_results (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id           INTEGER NOT NULL UNIQUE,
            sentiment_label      TEXT,
            sentiment_score      REAL,
            sentiment_confidence REAL,
            topics               TEXT,
            keywords             TEXT,
            entities             TEXT,
            processed_at         TEXT NOT NULL,
            model_version        TEXT NOT NULL DEFAULT 'v1.0',
            FOREIGN KEY (article_id)
                REFERENCES articles(id)
                ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_nlp_article_id
        ON nlp_results(article_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_nlp_sentiment
        ON nlp_results(sentiment_label)
    """)

    conn.commit()
    logger.info(f"[{MIGRATION_ID}] selesai — {DESCRIPTION}")


def down(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS nlp_results")
    conn.commit()
    logger.info(f"[{MIGRATION_ID}] rolled back — table dihapus")