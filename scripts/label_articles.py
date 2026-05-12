# scripts/label_articles.py
"""
Interactive labeling tool untuk artikel telco.
Jalankan di terminal, label satu per satu.
Progress disimpan otomatis — bisa dilanjutkan kalau interrupted.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
from datetime import datetime, timezone

TRAINING_DB = "data/training_data.db"

LABEL_MAP = {
    "p": "positive",
    "n": "negative",
    "u": "neutral",
    "s": "skip",
}

LABEL_GUIDE = """
PANDUAN LABELING ARTIKEL TELCO:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
positive  [p] → berita menguntungkan kompetitor
               contoh: luncurkan produk baru, revenue naik,
                       ekspansi jaringan, award, partnership

negative  [n] → berita merugikan kompetitor
               contoh: rugi, gangguan jaringan, complaint,
                       turun pendapatan, masalah regulasi,
                       PHK, akuisisi gagal

neutral   [u] → berita faktual tanpa tone positif/negatif
               contoh: pergantian direksi (tanpa konteks),
                       laporan keuangan flat, event biasa,
                       pengumuman tanpa dampak jelas

skip      [s] → artikel tidak relevan atau tidak cukup info
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""


def get_unlabeled(conn: sqlite3.Connection) -> list:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, judul, summary, source_nama, published
        FROM training_articles
        WHERE sentiment_label IS NULL
        ORDER BY relevance_score DESC, id
    """)
    return cursor.fetchall()


def save_label(
    conn: sqlite3.Connection,
    article_id: int,
    label: str
) -> None:
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE training_articles
        SET sentiment_label = ?,
            label_source    = 'manual',
            labeled_at      = ?
        WHERE id = ?
    """, (
        label,
        datetime.now(timezone.utc).isoformat(),
        article_id
    ))
    conn.commit()


def print_progress(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN sentiment_label IS NOT NULL THEN 1 ELSE 0 END) as labeled
        FROM training_articles
    """)
    total, labeled = cursor.fetchone()
    remaining = total - labeled

    cursor.execute("""
        SELECT sentiment_label, COUNT(*)
        FROM training_articles
        WHERE sentiment_label IS NOT NULL
        GROUP BY sentiment_label
    """)
    dist = dict(cursor.fetchall())

    print(f"\n  Progress: {labeled}/{total} artikel dilabel")
    print(f"  Remaining: {remaining}")
    print(f"  positive : {dist.get('positive', 0)}")
    print(f"  negative : {dist.get('negative', 0)}")
    print(f"  neutral  : {dist.get('neutral', 0)}")


def run_labeling():
    conn = sqlite3.connect(TRAINING_DB)
    articles = get_unlabeled(conn)

    if not articles:
        print("Semua artikel sudah dilabel!")
        print_progress(conn)
        conn.close()
        return

    print(LABEL_GUIDE)
    print(f"Total artikel belum dilabel: {len(articles)}")
    print("Tekan Ctrl+C kapan saja untuk berhenti — progress tersimpan otomatis.\n")

    labeled_count = 0

    for idx, (article_id, judul, summary, source, published) in enumerate(articles, 1):
        print("=" * 60)
        print(f"[{idx}/{len(articles)}] ID: {article_id}")
        print(f"Source   : {source}")
        print(f"Published: {published}")
        print(f"\nJUDUL:\n{judul}")
        if summary:
            # Truncate summary panjang
            display_summary = summary[:400] + "..." if len(summary) > 400 else summary
            print(f"\nSUMMARY:\n{display_summary}")
        print()

        while True:
            try:
                choice = input(
                    "Label [p=positive / n=negative / u=neutral / s=skip]: "
                ).strip().lower()

                if choice not in LABEL_MAP:
                    print("Input tidak valid. Gunakan: p, n, u, atau s")
                    continue

                label = LABEL_MAP[choice]

                if label == "skip":
                    print("  → Skipped")
                else:
                    save_label(conn, article_id, label)
                    labeled_count += 1
                    print(f"  → Saved: {label}")

                break

            except KeyboardInterrupt:
                print(f"\n\nLabeling dihentikan. {labeled_count} artikel dilabel.")
                print_progress(conn)
                conn.close()
                sys.exit(0)

    print(f"\n✅ Semua artikel selesai dilabel!")
    print_progress(conn)
    conn.close()


if __name__ == "__main__":
    run_labeling()