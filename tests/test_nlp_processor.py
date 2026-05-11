# tests/test_nlp_processor.py

import json
import sqlite3
import tempfile
import os
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion.nlp_processor import (
    clean_text,
    truncate_for_model,
    analyze_sentiment,
    extract_keywords,
    detect_competitor_mentions,
    save_nlp_result,
    save_competitor_mentions,
    SENTIMENT_MAP,
    MODEL_VERSION,
)


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def test_db():
    """Temporary database untuk testing — isolated dari production."""
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
        CREATE TABLE nlp_results (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id           INTEGER NOT NULL UNIQUE,
            sentiment_label      TEXT,
            sentiment_score      REAL,
            sentiment_confidence REAL,
            topics               TEXT,
            keywords             TEXT,
            processed_at         TEXT NOT NULL,
            model_version        TEXT NOT NULL DEFAULT 'v1.0',
            FOREIGN KEY (article_id) REFERENCES articles(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE competitor_mentions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id      INTEGER NOT NULL,
            competitor      TEXT NOT NULL,
            mention_count   INTEGER DEFAULT 1,
            sentiment_score REAL,
            FOREIGN KEY (article_id) REFERENCES articles(id),
            UNIQUE(article_id, competitor)
        )
    """)

    cursor.executemany("""
        INSERT INTO articles
        (guid, judul, url, collected_at, content_fetched)
        VALUES (?, ?, ?, '2026-05-11', 1)
    """, [
        ("guid-1", "Telkomsel Luncurkan 5G",   "https://example.com/1"),
        ("guid-2", "Indosat Akuisisi Startup",  "https://example.com/2"),
        ("guid-3", "XL Axiata Rugi Q1 2026",    "https://example.com/3"),
    ])

    conn.commit()
    yield conn, db_path
    conn.close()
    os.unlink(db_path)


@pytest.fixture
def sample_corpus():
    return [
        "Telkomsel meluncurkan paket internet 5G tercepat di Indonesia dengan harga terjangkau untuk pelanggan",
        "Indosat Ooredoo mengakuisisi startup teknologi untuk memperkuat layanan digital enterprise",
        "XL Axiata mencatat kerugian pada kuartal pertama akibat persaingan harga paket data yang ketat",
        "Operator seluler bersaing memperebutkan lisensi frekuensi 700 MHz dari pemerintah Indonesia",
        "Biznet Networks memperluas jaringan fiber optik ke kota-kota tier dua di Jawa dan Sumatra",
    ]


# ============================================================
# TESTS — TEXT PREPROCESSING
# ============================================================

def test_clean_text_removes_url():
    text   = "Baca selengkapnya di https://detik.com/berita artikel ini"
    result = clean_text(text)
    assert "https://" not in result
    assert "artikel ini" in result


def test_clean_text_handles_empty():
    assert clean_text("") == ""
    assert clean_text(None) == ""


def test_truncate_for_model():
    long_text = "kata " * 1000
    result    = truncate_for_model(long_text, max_chars=100)
    assert len(result) <= 100


def test_truncate_short_text_unchanged():
    short = "Telkomsel luncurkan paket baru"
    assert truncate_for_model(short) == short


# ============================================================
# TESTS — KEYWORD EXTRACTION
# ============================================================

def test_extract_keywords_returns_list(sample_corpus):
    keywords = extract_keywords(sample_corpus, article_idx=0)
    assert isinstance(keywords, list)
    assert len(keywords) > 0


def test_extract_keywords_single_doc_returns_empty():
    """Corpus dengan 1 dokumen tidak bisa menghasilkan IDF yang meaningful."""
    result = extract_keywords(["satu dokumen saja"], article_idx=0)
    assert result == []


def test_extract_keywords_count(sample_corpus):
    keywords = extract_keywords(sample_corpus, article_idx=0, n_keywords=5)
    assert len(keywords) <= 5


# ============================================================
# TESTS — COMPETITOR DETECTION
# ============================================================

def test_detect_mentions_finds_brand():
    text     = "Telkomsel meluncurkan paket 5G terbaru di Indonesia"
    mentions = detect_competitor_mentions(text, sentiment_score=0.8)

    competitors = [m["competitor"] for m in mentions]
    assert "Telkomsel" in competitors


def test_detect_mentions_word_boundary():
    """'sindikat' tidak boleh match keyword 'isat' dari Indosat."""
    text     = "321 WNA sindikat judol ditangkap polisi"
    mentions = detect_competitor_mentions(text, sentiment_score=0.0)

    competitors = [m["competitor"] for m in mentions]
    assert "Indosat" not in competitors


def test_detect_mentions_multiple_brands():
    text     = "Telkomsel dan Indosat bersaing memperebutkan frekuensi 700 MHz"
    mentions = detect_competitor_mentions(text, sentiment_score=0.5)

    competitors = [m["competitor"] for m in mentions]
    assert "Telkomsel" in competitors
    assert "Indosat"   in competitors


def test_detect_mentions_sentiment_passed():
    text     = "XL Axiata mencatat kerugian besar"
    mentions = detect_competitor_mentions(text, sentiment_score=-0.7)

    xl_mention = next(
        (m for m in mentions if m["competitor"] == "XL Axiata"), None
    )
    assert xl_mention is not None
    assert xl_mention["sentiment_score"] == -0.7


# ============================================================
# TESTS — DATABASE OPERATIONS
# ============================================================

def test_save_nlp_result_updates_nlp_processed(test_db):
    conn, _ = test_db

    save_nlp_result(
        conn,
        article_id=1,
        sentiment_label="positive",
        sentiment_score=0.8,
        sentiment_confidence=0.95,
        topics=[["jaringan", "5g", "internet"]],
        keywords=["telkomsel", "5g", "paket"]
    )

    cursor = conn.cursor()
    cursor.execute(
        "SELECT nlp_processed FROM articles WHERE id=1"
    )
    assert cursor.fetchone()[0] == 1


def test_save_nlp_result_stores_json(test_db):
    conn, _ = test_db
    keywords = ["telkomsel", "5g", "paket", "internet"]
    topics   = [["jaringan", "5g"], ["harga", "paket"]]

    save_nlp_result(
        conn, 1, "positive", 0.8, 0.95, topics, keywords
    )

    cursor = conn.cursor()
    cursor.execute(
        "SELECT keywords, topics FROM nlp_results WHERE article_id=1"
    )
    row = cursor.fetchone()

    assert json.loads(row[0]) == keywords
    assert json.loads(row[1]) == topics


def test_save_competitor_mentions_idempotent(test_db):
    conn, _ = test_db
    mentions = [{"competitor": "Telkomsel", "mention_count": 3, "sentiment_score": 0.8}]

    save_competitor_mentions(conn, article_id=1, mentions=mentions)
    save_competitor_mentions(conn, article_id=1, mentions=mentions)

    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM competitor_mentions WHERE article_id=1"
    )
    assert cursor.fetchone()[0] == 1