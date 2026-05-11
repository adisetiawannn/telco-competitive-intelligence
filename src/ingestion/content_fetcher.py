# this pyfile is for content fetching related functions, e.g. fetch_content_for_article
# was builded after we added m001_alter_articles.py migration, so we can track content_fetched and fetch_attempts in articles table.
# this file is not for NLP processing, which will be in nlp_processor.py


import ssl
import certifi
ssl._create_default_https_context = ssl.create_default_context

import sqlite3
import time
import logging
import fcntl
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict

from newspaper import Article
from newspaper import ArticleException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS
# ===========================================================

DB_PATH = "data/articles.db"
LOCK_FILE = "data/fetcher.lock"
RATE_LIMIT = 1.5 #seconds
MAX_RETRIES = 3
MIN_CONTENT = 200 # minimal jumlah karakter untuk dianggap valid

# State Codes
STATE_PENDING = 0
STATE_FETCHED = 1
STATE_FAILED = -1
STATE_SKIPPED = 2

# ============================================================
# FILE LOCK — cegah dua process jalan bersamaan
# ============================================================
def acquire_lock():
    """
    Acquire exclusive file lock.
    Raise RuntimeError kalau process lain sedang berjalan.
    """
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        logger.info("File lock acquired")
        return lock
    except BlockingIOError:
        raise RuntimeError(
            "Content fetcher sedang berjalan di process lain. "
            "Tunggu sampai selesai atau hapus data/fetcher.lock"
        )


def release_lock(lock) -> None:
    """Release file lock."""
    fcntl.flock(lock, fcntl.LOCK_UN)
    lock.close()
    Path(LOCK_FILE).unlink(missing_ok=True)
    logger.info("File lock released")


# ============================================================
# DATABASE HELPERS
# ============================================================

def get_pending_articles(conn: sqlite3.Connection):
    """
    Return artikel yang belum di-fetch atau perlu di-retry.
    Resume-capable: hanya ambil yang belum selesai.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, url, judul
        FROM articles
        WHERE content_fetched = 0
           OR (content_fetched = -1 AND fetch_attempts < ?)
        ORDER BY published DESC
    """, (MAX_RETRIES,))
    return cursor.fetchall()


def save_content(
    conn: sqlite3.Connection,
    article_id: int,
    full_content: str
) -> None:
    """Simpan full content ke table article_contents."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO article_contents
        (article_id, full_content, content_length, fetched_at)
        VALUES (?, ?, ?, ?)
    """, (
        article_id,
        full_content,
        len(full_content),
        datetime.now(timezone.utc).isoformat()
    ))

    cursor.execute("""
        UPDATE articles
        SET content_fetched = ?,
            processing_error = NULL
        WHERE id = ?
    """, (STATE_FETCHED, article_id))

    conn.commit()


def mark_failed(
    conn: sqlite3.Connection,
    article_id: int,
    error: str
) -> None:
    """Tandai artikel sebagai failed."""
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE articles
        SET content_fetched  = ?,
            fetch_attempts   = fetch_attempts + 1,
            processing_error = ?
        WHERE id = ?
    """, (STATE_FAILED, error[:500], article_id))
    conn.commit()


def mark_skipped(
    conn: sqlite3.Connection,
    article_id: int,
    reason: str
) -> None:
    """Tandai artikel sebagai skipped."""
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE articles
        SET content_fetched  = ?,
            processing_error = ?
        WHERE id = ?
    """, (STATE_SKIPPED, reason, article_id))
    conn.commit()


# ============================================================
# CORE FETCH LOGIC
# ============================================================

def fetch_article_content(url: str) -> Optional[str]:
    """
    Fetch dan extract full text dari URL menggunakan newspaper3k.
    """
    try:
        artikel = Article(url, language='id')
        artikel.download()
        artikel.parse()
        return artikel.text if artikel.text else None
    except ArticleException as e:
        raise ValueError(f"Article fetch failed: {e}")
    except Exception as e:
        raise ValueError(f"Unexpected error: {e}")

# ============================================================
# MAIN PIPELINE
# ============================================================

def run_fetch() -> Dict:
    """
    Main function — fetch full content untuk semua artikel pending.
    Resume-capable, rate-limited, dengan file lock.
    """
    lock = None

    stats = {
        "total_pending":  0,
        "total_fetched":  0,
        "total_skipped":  0,
        "total_failed":   0,
    }

    try:
        lock = acquire_lock()
        conn = sqlite3.connect(DB_PATH)

        pending = get_pending_articles(conn)
        stats["total_pending"] = len(pending)

        if not pending:
            logger.info("Tidak ada artikel pending. Semua sudah di-fetch.")
            return stats

        logger.info(f"Memulai fetch untuk {len(pending)} artikel...")

        for idx, (article_id, url, judul) in enumerate(pending, 1):
            logger.info(
                f"[{idx}/{len(pending)}] Fetching: {judul[:50]}..."
            )

            try:
                content = fetch_article_content(url)

                if content is None:
                    mark_skipped(conn, article_id, "empty content")
                    stats["total_skipped"] += 1
                    logger.warning(f"  → Skipped: empty content")

                elif len(content) < MIN_CONTENT:
                    mark_skipped(
                        conn, article_id,
                        f"content too short: {len(content)} chars"
                    )
                    stats["total_skipped"] += 1
                    logger.warning(
                        f"  → Skipped: terlalu pendek "
                        f"({len(content)} chars)"
                    )

                else:
                    save_content(conn, article_id, content)
                    stats["total_fetched"] += 1
                    logger.info(
                        f"  → Fetched: {len(content)} chars"
                    )

            except ValueError as e:
                mark_failed(conn, article_id, str(e))
                stats["total_failed"] += 1
                logger.error(f"  → Failed: {e}")

            time.sleep(RATE_LIMIT)

        conn.close()

    except RuntimeError as e:
        logger.error(f"Lock error: {e}")
        raise

    finally:
        if lock:
            release_lock(lock)

    logger.info(f"Fetch complete: {stats}")
    return stats


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    stats = run_fetch()

    print("\n=== FETCH SUMMARY ===")
    print(f"  Total pending : {stats['total_pending']}")
    print(f"  Fetched       : {stats['total_fetched']}")
    print(f"  Skipped       : {stats['total_skipped']}")
    print(f"  Failed        : {stats['total_failed']}")