# scripts/download_smsa_dataset.py
"""
Download SmSA dataset dari IndoNLU GitHub.
Simpan ke training_data.db sebagai foundation untuk fine-tuning.
SmSA = Sentence-level Multi-domain Sentiment Analysis
Domain: review makanan, hotel, produk — Bahasa Indonesia
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
import requests
import logging
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

TRAINING_DB = "data/training_data.db"
BASE_URL    = (
    "https://raw.githubusercontent.com/IndoNLP/indonlu"
    "/master/dataset/smsa_doc-sentiment-prosa"
)

SPLITS = {
    "train": f"{BASE_URL}/train_preprocess.tsv",
    "valid": f"{BASE_URL}/valid_preprocess.tsv",
    "test":  f"{BASE_URL}/test_preprocess.tsv",
}

VALID_LABELS = {"positive", "negative", "neutral"}


def init_smsa_table(conn: sqlite3.Connection) -> None:
    """
    Tambah table terpisah untuk SmSA dataset.
    Terpisah dari training_articles agar bisa track source-nya.
    """
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS smsa_dataset (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            text            TEXT NOT NULL,
            sentiment_label TEXT NOT NULL,
            split           TEXT NOT NULL,
            source          TEXT DEFAULT 'smsa_indonlu',
            collected_at    TEXT NOT NULL
        )
    """)
    conn.commit()
    logger.info("Table smsa_dataset ready.")


def download_and_parse(url: str, split: str) -> list[dict]:
    """Download dan parse satu split dari SmSA dataset."""
    logger.info(f"Downloading {split} from {url}...")

    response = requests.get(url, timeout=30)
    response.raise_for_status()

    rows    = []
    skipped = 0

    for line in response.text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        # Format: teks\tlabel
        # Label ada di akhir, teks bisa mengandung tab
        parts = line.rsplit("\t", 1)

        if len(parts) != 2:
            # Coba split by spasi di akhir kalau tidak ada tab
            parts = line.rsplit(" ", 1)

        if len(parts) != 2:
            skipped += 1
            continue

        text, label = parts
        text  = text.strip()
        label = label.strip().lower()

        if label not in VALID_LABELS:
            skipped += 1
            continue

        if len(text) < 10:
            skipped += 1
            continue

        rows.append({
            "text":  text,
            "label": label,
            "split": split,
        })

    logger.info(
        f"  → {len(rows)} rows parsed, {skipped} skipped"
    )
    return rows


def save_to_db(
    conn: sqlite3.Connection,
    rows: list[dict]
) -> int:
    """Simpan rows ke smsa_dataset table."""
    cursor = conn.cursor()
    saved  = 0

    for row in rows:
        cursor.execute("""
            INSERT INTO smsa_dataset
            (text, sentiment_label, split, collected_at)
            VALUES (?, ?, ?, ?)
        """, (
            row["text"],
            row["label"],
            row["split"],
            datetime.now(timezone.utc).isoformat()
        ))
        saved += 1

    conn.commit()
    return saved


def print_distribution(conn: sqlite3.Connection) -> None:
    """Print distribusi label untuk verifikasi class balance."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            split,
            sentiment_label,
            COUNT(*) as total
        FROM smsa_dataset
        GROUP BY split, sentiment_label
        ORDER BY split, sentiment_label
    """)

    print("\n=== DISTRIBUSI LABEL ===")
    current_split = None
    for split, label, count in cursor.fetchall():
        if split != current_split:
            print(f"\n  [{split}]")
            current_split = split
        print(f"    {label:10s}: {count:5d}")


if __name__ == "__main__":
    conn = sqlite3.connect(TRAINING_DB)
    init_smsa_table(conn)

    total_saved = 0

    for split, url in SPLITS.items():
        rows  = download_and_parse(url, split)
        saved = save_to_db(conn, rows)
        total_saved += saved
        logger.info(f"Saved {saved} rows for split={split}")

    print(f"\n=== SMSA DOWNLOAD COMPLETE ===")
    print(f"  Total saved: {total_saved}")

    print_distribution(conn)
    conn.close()