# tests/test_content_fetcher.py

import sqlite3
import pytest
import tempfile
import os
from unittest.mock import patch, MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion.content_fetcher import (
    get_pending_articles,
    save_content,
    mark_failed,
    mark_skipped,
    fetch_article_content,
    STATE_PENDING,
    STATE_FETCHED,
    STATE_FAILED,
    STATE_SKIPPED,
    MIN_CONTENT,
)


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def test_db():
    """
    Buat temporary database untuk testing.
    Dihapus otomatis setelah test selesai.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE articles (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            guid             TEXT UNIQUE NOT NULL,
            judul            TEXT NOT NULL,
            url              TEXT NOT NULL,
            summary          TEXT,
            published        TEXT,
            source_nama      TEXT,
            kompetitor       TEXT,
            collected_at     TEXT NOT NULL,
            content_fetched  INTEGER DEFAULT 0,
            nlp_processed    INTEGER DEFAULT 0,
            processing_error TEXT,
            fetch_attempts   INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE article_contents (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id     INTEGER NOT NULL UNIQUE,
            full_content   TEXT,
            content_length INTEGER,
            fetched_at     TEXT NOT NULL,
            FOREIGN KEY (article_id) REFERENCES articles(id)
        )
    """)

    # Insert sample articles
    cursor.executemany("""
        INSERT INTO articles (guid, judul, url, collected_at, content_fetched)
        VALUES (?, ?, ?, '2026-05-10', ?)
    """, [
        ("guid-1", "Artikel Telkomsel", "https://example.com/1", STATE_PENDING),
        ("guid-2", "Artikel XL Axiata", "https://example.com/2", STATE_PENDING),
        ("guid-3", "Artikel Indosat",   "https://example.com/3", STATE_FAILED),
        ("guid-4", "Artikel Biznet",    "https://example.com/4", STATE_FETCHED),
    ])

    conn.commit()
    yield conn, db_path
    conn.close()
    os.unlink(db_path)


# ============================================================
# TESTS
# ============================================================

def test_get_pending_articles_returns_only_pending(test_db):
    """Hanya artikel pending dan failed-retryable yang di-return."""
    conn, _ = test_db
    pending = get_pending_articles(conn)

    ids = [row[0] for row in pending]

    assert len(pending) == 3       # guid-1, guid-2, guid-3
    assert 4 not in ids            # guid-4 sudah fetched, tidak boleh muncul


def test_save_content_updates_state(test_db):
    """Setelah save_content, state harus jadi STATE_FETCHED."""
    conn, _ = test_db
    article_id = 1
    content    = "x" * 300    # 300 chars — di atas MIN_CONTENT

    save_content(conn, article_id, content)

    cursor = conn.cursor()
    cursor.execute(
        "SELECT content_fetched FROM articles WHERE id=?",
        (article_id,)
    )
    assert cursor.fetchone()[0] == STATE_FETCHED


def test_save_content_stores_in_article_contents(test_db):
    """Full content harus tersimpan di table article_contents."""
    conn, _ = test_db
    article_id = 1
    content    = "Telkomsel meluncurkan paket baru " * 20

    save_content(conn, article_id, content)

    cursor = conn.cursor()
    cursor.execute(
        "SELECT full_content, content_length FROM article_contents "
        "WHERE article_id=?",
        (article_id,)
    )
    row = cursor.fetchone()

    assert row is not None
    assert row[0] == content
    assert row[1] == len(content)


def test_mark_failed_increments_attempts(test_db):
    """Setiap kali failed, fetch_attempts harus increment."""
    conn, _ = test_db
    article_id = 1

    mark_failed(conn, article_id, "timeout error")
    mark_failed(conn, article_id, "timeout error")

    cursor = conn.cursor()
    cursor.execute(
        "SELECT fetch_attempts, content_fetched FROM articles WHERE id=?",
        (article_id,)
    )
    row = cursor.fetchone()

    assert row[0] == 2              # 2x failed = 2 attempts
    assert row[1] == STATE_FAILED


def test_mark_skipped_sets_correct_state(test_db):
    """Artikel yang di-skip harus punya state STATE_SKIPPED."""
    conn, _ = test_db
    article_id = 2

    mark_skipped(conn, article_id, "content too short: 50 chars")

    cursor = conn.cursor()
    cursor.execute(
        "SELECT content_fetched, processing_error FROM articles WHERE id=?",
        (article_id,)
    )
    row = cursor.fetchone()

    assert row[0] == STATE_SKIPPED
    assert "too short" in row[1]


def test_save_content_idempotent(test_db):
    """Save content dua kali ke artikel yang sama tidak boleh error."""
    conn, _ = test_db
    article_id = 1
    content    = "Konten artikel " * 30

    save_content(conn, article_id, content)
    save_content(conn, article_id, content)    # kedua kali tidak boleh crash

    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM article_contents WHERE article_id=?",
        (article_id,)
    )
    assert cursor.fetchone()[0] == 1    # hanya 1 row, bukan 2