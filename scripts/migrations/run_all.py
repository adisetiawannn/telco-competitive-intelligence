"""
Migration runner — jalankan semua migration secara berurutan.
Aman dijalankan berkali-kali (idempotent).
"""

import sqlite3
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))

from scripts.migrations import (
    m001_alter_articles,
    m002_article_contents,
    m003_nlp_results,
    m004_competitor_mentions,
    m005_competitor_daily_stats,
    m006_fetch_attempts,
    m006_fetch_attempts,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

DB_PATH    = "data/articles.db"

# Tambahkan ke list MIGRATIONS
MIGRATIONS = [
    m001_alter_articles,
    m002_article_contents,
    m003_nlp_results,
    m004_competitor_mentions,
    m005_competitor_daily_stats,
    m006_fetch_attempts,
]


def run_migrations(direction: str = "up") -> None:
    conn = sqlite3.connect(DB_PATH)

    try:
        logger.info(f"Menjalankan {len(MIGRATIONS)} migrations [{direction}]...")

        targets = MIGRATIONS if direction == "up" else reversed(MIGRATIONS)

        for migration in targets:
            logger.info(
                f"→ [{migration.MIGRATION_ID}] {migration.DESCRIPTION}"
            )
            getattr(migration, direction)(conn)

        logger.info("Semua migrations selesai.")

    except Exception as e:
        logger.error(f"Migration gagal: {e}")
        conn.rollback()
        raise

    finally:
        conn.close()


def verify_schema() -> None:
    """Verifikasi semua table yang diharapkan ada."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    expected_tables = [
        "articles",
        "article_contents",
        "nlp_results",
        "competitor_mentions",
        "competitor_daily_stats",
    ]

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    existing = {row[0] for row in cursor.fetchall()}

    print("\n=== VERIFIKASI SCHEMA ===")
    all_ok = True

    for table in expected_tables:
        status = "✅" if table in existing else "❌"
        print(f"  {status} {table}")
        if table not in existing:
            all_ok = False

    print("\n=== VERIFIKASI COLUMNS articles ===")
    expected_cols = [
        "id", "guid", "judul", "url", "summary",
        "published", "source_nama", "kompetitor",
        "collected_at", "content_fetched",
        "nlp_processed", "processing_error"
    ]

    cursor.execute("PRAGMA table_info(articles)")
    existing_cols = {row[1] for row in cursor.fetchall()}

    for col in expected_cols:
        status = "✅" if col in existing_cols else "❌"
        print(f"  {status} {col}")
        if col not in existing_cols:
            all_ok = False

    conn.close()

    if all_ok:
        print("\n✅ Schema verified — semua table dan kolom ada.")
    else:
        print("\n❌ Ada yang missing — cek error di atas.")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "up"

    if command == "up":
        run_migrations("up")
        verify_schema()
    elif command == "down":
        confirm = input(
            "Rollback SEMUA migrations? Data bisa hilang. "
            "(ketik 'rollback' untuk konfirmasi): "
        )
        if confirm.strip().lower() == "rollback":
            run_migrations("down")
        else:
            print("Rollback dibatalkan.")
    elif command == "verify":
        verify_schema()
    else:
        print(f"Command tidak dikenal: {command}")
        print("Gunakan: python -m scripts.migrations.run_all [up|down|verify]")