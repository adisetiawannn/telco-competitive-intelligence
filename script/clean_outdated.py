# scripts/clean_outdated.py

import sqlite3
import email.utils
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = "data/articles.db"
MAX_DAYS = 60


def parse_date_robust(published_str: str):
    """
    Parse tanggal dengan multiple fallback strategy.
    Return datetime object atau None kalau benar-benar tidak bisa di-parse.
    """
    if not published_str:
        return None

    # Strategy 1 — RFC 2822 standard parser
    try:
        parsed = email.utils.parsedate_to_datetime(published_str)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        pass

    # Strategy 2 — Manual parsing dengan format umum RSS
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",      # Wed, 30 Aug 2023 07:00:00 +0000
        "%a, %d %b %Y %H:%M:%S GMT",     # Wed, 30 Aug 2023 07:00:00 GMT
        "%a, %d %b %Y %H:%M:%S",         # Wed, 30 Aug 2023 07:00:00
        "%Y-%m-%dT%H:%M:%S%z",           # ISO format
        "%Y-%m-%d %H:%M:%S",             # Simple format
    ]

    for fmt in formats:
        try:
            parsed = datetime.strptime(published_str.strip(), fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            continue

    return None


def preview_outdated():
    """Preview artikel yang akan dihapus tanpa menghapus."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id, source_nama, judul, published FROM articles")
    rows = cursor.fetchall()

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_DAYS)
    outdated = []
    parse_failed = []  # ← track artikel yang gagal di-parse

    for row in rows:
        id_, source, judul, published = row

        if not published:
            continue

        parsed = parse_date_robust(published)

        if parsed is None:
            parse_failed.append({
                "id": id_,
                "source": source,
                "published": published,
                "judul": judul[:60]
            })
            continue

        if parsed < cutoff:
            outdated.append({
                "id": id_,
                "source": source,
                "judul": judul[:60],
                "published": published,
                "parsed_date": parsed
            })

    conn.close()

    # Sort berdasarkan tanggal aktual yang sudah di-parse
    outdated.sort(key=lambda x: x["parsed_date"])

    return outdated, parse_failed


def delete_outdated(outdated_ids: list):
    """Hapus artikel berdasarkan list ID yang sudah diverifikasi."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    placeholders = ",".join("?" * len(outdated_ids))
    cursor.execute(
        f"DELETE FROM articles WHERE id IN ({placeholders})",
        outdated_ids
    )

    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted


if __name__ == "__main__":
    print("=== STEP 1: PREVIEW OUTDATED ARTICLES ===")
    outdated, parse_failed = preview_outdated()

    print(f"\nDitemukan {len(outdated)} artikel outdated (> {MAX_DAYS} hari)")

    if parse_failed:
        print(f"\n⚠️  {len(parse_failed)} artikel TIDAK BISA di-parse tanggalnya:")
        for art in parse_failed[:5]:
            print(f"  [{art['id']}] published='{art['published']}'")
            print(f"       {art['judul']}")
        print("  → Artikel ini di-skip, tidak akan dihapus")

    if not outdated:
        print("\n✅ Tidak ada artikel outdated. Database bersih.")
        exit(0)

    # Distribusi per source
    from collections import Counter
    source_count = Counter(a["source"] for a in outdated)

    print("\nDistribusi per source:")
    for source, count in source_count.most_common():
        print(f"  {count:4d} artikel — {source}")

    print("\nSample 10 artikel TERTUA:")
    for artikel in outdated[:10]:
        print(f"  [{artikel['id']}] {artikel['published']}")
        print(f"       {artikel['judul']}")
        print(f"       Source: {artikel['source']}")
        print()

    # Konfirmasi sebelum hapus
    print(f"\n{'='*60}")
    confirm = input(
        f"Hapus {len(outdated)} artikel outdated? "
        f"(ketik 'hapus' untuk konfirmasi): "
    )

    if confirm.strip().lower() == "hapus":
        ids_to_delete = [a["id"] for a in outdated]
        deleted = delete_outdated(ids_to_delete)
        print(f"\n✅ {deleted} artikel berhasil dihapus.")

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM articles")
        remaining = cursor.fetchone()[0]
        conn.close()
        print(f"✅ Sisa artikel di database: {remaining}")
    else:
        print("\n❌ Penghapusan dibatalkan. Tidak ada data yang dihapus.")