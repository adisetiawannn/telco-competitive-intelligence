# scripts/collect_training_data.py
"""
Script khusus untuk mengumpulkan historical data sebagai training dataset.
BERBEDA dari rss_collector.py yang hanya ambil artikel recent (60 hari).
Script ini:
- Tidak ada date filter
- Simpan ke database terpisah agar tidak campur dengan inference data
- Target: 200+ artikel untuk fine-tuning Phase 3
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import ssl
import certifi
ssl._create_default_https_context = ssl.create_default_context

import sys
import sqlite3
import logging
import feedparser
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from configs.sources import (
    load_sources_from_yaml,
    hitung_relevansi_score,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Database TERPISAH dari production
TRAINING_DB = "data/training_data.db"


def init_training_db(conn: sqlite3.Connection) -> None:
    """Buat schema untuk training database."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS training_articles (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            guid         TEXT UNIQUE NOT NULL,
            judul        TEXT NOT NULL,
            url          TEXT NOT NULL,
            summary      TEXT,
            published    TEXT,
            source_nama  TEXT,
            kompetitor   TEXT,
            collected_at TEXT NOT NULL,
            relevance_score INTEGER DEFAULT 0,
            -- Label untuk fine-tuning (diisi manual atau weak supervision)
            sentiment_label TEXT DEFAULT NULL,
            label_source    TEXT DEFAULT NULL,
            labeled_at      TEXT DEFAULT NULL
        )
    """)
    conn.commit()
    logger.info("Training DB initialized.")


def collect_training_articles() -> dict:
    """
    Collect artikel dari semua sources tanpa date filter.
    Simpan ke training_data.db.
    """
    stats = {
        "total_fetched":  0,
        "total_relevant": 0,
        "total_saved":    0,
        "duplicates":     0,
    }

    Path("data").mkdir(exist_ok=True)
    conn = sqlite3.connect(TRAINING_DB)
    init_training_db(conn)
    cursor = conn.cursor()

    sources = load_sources_from_yaml()
    logger.info(f"Processing {len(sources)} sources (NO date filter)...")

    for source in sources:
        logger.info(f"Parsing: {source.nama}")

        try:
            feed = feedparser.parse(source.url)
            entries = feed.entries
            stats["total_fetched"] += len(entries)

            for entry in entries:
                judul     = str(entry.get("title",   "") or "").strip()
                summary   = str(entry.get("summary", "") or "").strip()
                url       = str(entry.get("link",    "") or "").strip()
                guid      = str(entry.get("id",      url) or url)
                published = str(entry.get("published", "") or "")

                if not judul or not url:
                    continue

                # Relevance check — tetap pakai scoring
                score = hitung_relevansi_score(judul, summary)
                if score < 2:
                    continue

                stats["total_relevant"] += 1

                try:
                    cursor.execute("""
                        INSERT OR IGNORE INTO training_articles
                        (guid, judul, url, summary, published,
                         source_nama, collected_at, relevance_score)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        guid, judul, url, summary, published,
                        source.nama,
                        datetime.now(timezone.utc).isoformat(),
                        score
                    ))

                    if cursor.rowcount > 0:
                        stats["total_saved"] += 1
                    else:
                        stats["duplicates"] += 1

                except sqlite3.IntegrityError:
                    stats["duplicates"] += 1

        except Exception as e:
            logger.error(f"Error parsing {source.nama}: {e}")

    conn.commit()
    conn.close()
    return stats


if __name__ == "__main__":
    stats = collect_training_articles()

    print("\n=== TRAINING DATA COLLECTION ===")
    print(f"  Total fetched  : {stats['total_fetched']}")
    print(f"  Relevant       : {stats['total_relevant']}")
    print(f"  Saved          : {stats['total_saved']}")
    print(f"  Duplicates     : {stats['duplicates']}")

    # Verifikasi
    conn = sqlite3.connect(TRAINING_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM training_articles")
    total = cursor.fetchone()[0]
    cursor.execute(
        "SELECT COUNT(*) FROM training_articles "
        "WHERE sentiment_label IS NOT NULL"
    )
    labeled = cursor.fetchone()[0]
    conn.close()

    print(f"\n  Total di DB    : {total}")
    print(f"  Sudah dilabel  : {labeled}")
    print(f"  Belum dilabel  : {total - labeled}")