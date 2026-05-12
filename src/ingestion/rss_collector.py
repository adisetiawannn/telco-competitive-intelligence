# SSL Fix untuk macOS + pyenv
import ssl
import certifi

ssl._create_default_https_context = lambda: ssl.create_default_context(
    cafile="/Users/960169/digital-hub/02-nlp-project/telco-competitive-intelligence/.venv/lib/python3.11/site-packages/certifi/cacert.pem"
)

import feedparser
import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from configs.sources import (
    get_active_sources,
    is_artikel_relevan,
    NewsSource,
    load_sources_from_yaml   # ← load yaml file from discovery results
)

# ============================================================
# Clean HTML dari summary sebelum filtering
# ============================================================

from bs4 import BeautifulSoup

def clean_html(teks: Optional[object]) -> str:
    """Hapus HTML tags dari teks menggunakan BeautifulSoup."""
    if not teks:
        return ""
    if isinstance(teks, list):
        teks = " ".join(str(item) for item in teks)
    elif not isinstance(teks, str):
        teks = str(teks)
    soup = BeautifulSoup(teks, "html.parser")
    return soup.get_text(separator=" ").strip()


# ============================================================
# Date Filte: cek apakah artikel masih dalam rentang waktu yang relevan
# ============================================================

from datetime import datetime, timezone, timedelta
import email.utils

def is_artikel_recent(published_str: str, max_days: int = 60) -> bool:
    """
    Check apakah artikel masih dalam rentang waktu yang relevan.
    Default: maksimal 60 hari ke belakang.
    Return True kalau recent, False kalau terlalu lama.
    """
    if not published_str:
        return True  # kalau tidak ada tanggal, anggap recent

    try:
        # RSS menggunakan format RFC 2822
        # contoh: "Fri, 05 May 2023 07:00:00 GMT"
        parsed_date = email.utils.parsedate_to_datetime(published_str)

        # Normalize ke UTC untuk comparison yang konsisten
        if parsed_date.tzinfo is None:
            parsed_date = parsed_date.replace(tzinfo=timezone.utc)

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=max_days)
        return parsed_date >= cutoff_date

    except Exception:
        return True  # kalau parsing gagal, anggap recent


# ============================================================
# LOGGING SETUP
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================
# DATABASE SETUP
# ============================================================

def get_db_path() -> Path:
    """Return path ke SQLite database."""
    db_dir = Path("data")
    db_dir.mkdir(exist_ok=True)
    return db_dir / "articles.db"


def init_database() -> sqlite3.Connection:
    """
    Inisialisasi database dan buat tabel jika belum ada.
    Menggunakan IF NOT EXISTS agar aman dipanggil berkali-kali.
    """
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            guid        TEXT UNIQUE NOT NULL,
            judul       TEXT NOT NULL,
            url         TEXT NOT NULL,
            summary     TEXT,
            published   TEXT,
            source_nama TEXT,
            kompetitor  TEXT,
            collected_at TEXT NOT NULL
        )
    """)

    conn.commit()
    logger.info("Database initialized successfully")
    return conn


# ============================================================
# CORE COLLECTION LOGIC
# ============================================================

def parse_feed(source: NewsSource) -> List[Dict]:
    """
    Parse RSS feed dari satu source.
    Return list of raw article dictionaries.
    """
    logger.info(f"Parsing feed: {source.nama}")

    try:
        feed = feedparser.parse(source.url)

        if feed.bozo:
            logger.warning(f"Feed {source.nama} has issues: {feed.bozo_exception}")

        articles = []
        for entry in feed.entries:
            artikel = {
                "guid":       entry.get("id", entry.get("link", "")),
                "judul":      entry.get("title", ""),
                "url":        entry.get("link", ""),
                "summary":      clean_html(entry.get("summary", "")),  # ← tambahkan clean_html,
                "published":  entry.get("published", ""),
                "source_nama": source.nama,
            }
            articles.append(artikel)

        logger.info(f"Found {len(articles)} articles from {source.nama}")
        return articles

    except Exception as e:
        logger.error(f"Failed to parse {source.nama}: {e}")
        return []


def is_duplicate(conn: sqlite3.Connection, guid: str) -> bool:
    """
    Check apakah artikel dengan guid ini sudah ada di database.
    Return True jika sudah ada (duplicate), False jika belum.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM articles WHERE guid = ?", (guid,))
    return cursor.fetchone() is not None


def save_article(conn: sqlite3.Connection, artikel: Dict) -> bool:
    """
    Simpan satu artikel ke database.
    Return True jika berhasil, False jika duplicate atau error.
    """
    if is_duplicate(conn, artikel["guid"]):
        return False

    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO articles 
            (guid, judul, url, summary, published, source_nama, kompetitor, collected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            artikel["guid"],
            artikel["judul"],
            artikel["url"],
            artikel["summary"],
            artikel["published"],
            artikel["source_nama"],
            artikel.get("kompetitor", "general"),
            datetime.now().isoformat()
        ))
        conn.commit()
        return True

    except Exception as e:
        logger.error(f"Failed to save article: {e}")
        return False


# ============================================================
# MAIN COLLECTION PIPELINE
# ============================================================

def run_collection() -> Dict:
    """
    Main function — jalankan seluruh collection pipeline.
    Return summary statistics.
    """
    logger.info("Starting collection pipeline...")

    conn = init_database()
    stats = {
        "total_fetched": 0,
        "total_relevant": 0,
        "total_saved": 0,
        "total_duplicate": 0,
        "total_outdated": 0,
        "sources_processed": 0
    }

    sources = load_sources_from_yaml() or get_active_sources()
    logger.info(f"Processing {len(sources)} active sources")

    for source in sources:
        articles = parse_feed(source)
        stats["total_fetched"] += len(articles)
        stats["sources_processed"] += 1

        for artikel in articles:
                    
            # relevansi da date filter
            # Filter 1 — relevance check
            if not is_artikel_relevan(artikel['judul'], artikel.get('summary', '')):
                continue

            # Filter 2 — date check (harus di sini, bukan setelah return)
            if not is_artikel_recent(artikel['published'], max_days=60):
                stats["total_outdated"] += 1
                continue

            stats["total_relevant"] += 1

            if save_article(conn, artikel):
                stats["total_saved"] += 1
                logger.info(f"Saved: {artikel['judul'][:60]}...")
            else:
                stats["total_duplicate"] += 1

    conn.close()
    logger.info(f"Collection complete: {stats}")
    return stats

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    stats = run_collection()
    print("\n=== COLLECTION SUMMARY ===")
    print(f"  Sources processed : {stats['sources_processed']}")
    print(f"  Total fetched     : {stats['total_fetched']}")
    print(f"  Relevant articles : {stats['total_relevant']}")
    print(f"  Newly saved       : {stats['total_saved']}")
    print(f"  Duplicates skipped: {stats['total_duplicate']}")
    print(f"  Outdated skipped  : {stats['total_outdated']}")