# src/intelligence/rag_pipeline.py
"""
RAG Pipeline — Phase 4 LLM Integration
Menggunakan ChromaDB + sentence-transformers + Gemini API
untuk generate competitive intelligence digest.

Stack:
- Embedding : paraphrase-multilingual-MiniLM-L12-v2 (lokal, gratis)
- Vector DB : ChromaDB PersistentClient (lokal, gratis)
- LLM       : Gemini 1.5 Flash (free tier, gratis)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import re
import json
import sqlite3
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import chromadb
from sentence_transformers import SentenceTransformer
from typing import Optional, Any
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS
# ============================================================

DB_PATH        = "data/articles.db"
CHROMA_PATH    = "data/chroma_db"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
GEMINI_MODEL    = "gemini-2.5-flash"  # model terbaru yang lebih cepat dan murah dari 1.5
COLLECTION_NAME = "telco_articles"
TOP_K          = 5       # jumlah artikel yang diretrieve per query
MAX_CONTENT    = 1500    # chars per artikel yang dikirim ke LLM


# ============================================================
# STEP 1 — TEXT CLEANING
# ============================================================

def clean_for_embedding(
    judul: str,
    summary: Optional[str],
    full_content: Optional[str]
) -> str:
    """
    Gabungkan dan bersihkan teks untuk embedding.

    Strategy:
    - Judul selalu disertakan — paling informatif untuk similarity
    - Summary sebagai context tambahan
    - Full content di-truncate — terlalu panjang untuk embedding

    Kenapa truncate bukan pakai semua:
    - Model embedding punya max token limit (256 tokens)
    - Teks terlalu panjang akan di-truncate oleh model anyway
    - 500 chars pertama biasanya paling informatif
    """
    parts = []

    # Judul — wajib ada
    if judul:
        parts.append(judul.strip())

    # Summary — context tambahan
    if summary:
        clean_summary = re.sub(r'<[^>]+>', ' ', summary)
        clean_summary = re.sub(r'\s+', ' ', clean_summary).strip()
        if len(clean_summary) > 10:
            parts.append(clean_summary[:300])

    # Full content — ambil awal saja
    if full_content:
        clean_content = re.sub(r'<[^>]+>', ' ', full_content)
        clean_content = re.sub(r'http\S+|www\S+', '', clean_content)
        clean_content = re.sub(r'\s+', ' ', clean_content).strip()
        if len(clean_content) > 10:
            parts.append(clean_content[:500])

    combined = ' '.join(parts)

    # Final cleanup
    combined = re.sub(r'\s+', ' ', combined).strip()

    return combined


def clean_for_llm(
    judul: str,
    summary: Optional[str],
    full_content: Optional[str],
    max_chars: int = MAX_CONTENT
) -> str:
    """
    Siapkan teks untuk dikirim ke LLM.
    Berbeda dari clean_for_embedding — lebih lengkap tapi tetap truncate.
    LLM butuh lebih banyak context dari embedding model.
    """
    parts = []

    if judul:
        parts.append(f"Judul: {judul.strip()}")

    if full_content and len(full_content) > 100:
        clean = re.sub(r'<[^>]+>', ' ', full_content)
        clean = re.sub(r'http\S+|www\S+', '', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        parts.append(f"Konten: {clean[:max_chars]}")
    elif summary:
        clean = re.sub(r'<[^>]+>', ' ', summary)
        clean = re.sub(r'\s+', ' ', clean).strip()
        parts.append(f"Ringkasan: {clean[:500]}")

    return '\n'.join(parts)

# ============================================================
# STEP 2 — INDEXING PIPELINE
# ============================================================

def load_articles_from_db(conn: sqlite3.Connection) -> list[dict]:
    """
    Load semua artikel yang sudah di-fetch dari database.
    Join dengan article_contents untuk full_content.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            a.id,
            a.judul,
            a.url,
            a.summary,
            a.published,
            a.source_nama,
            a.kompetitor,
            ac.full_content,
            nr.sentiment_label,
            nr.sentiment_score
        FROM articles a
        LEFT JOIN article_contents ac ON a.id = ac.article_id
        LEFT JOIN nlp_results nr      ON a.id = nr.article_id
        WHERE a.content_fetched = 1
        ORDER BY a.published DESC
    """)

    articles = []
    for row in cursor.fetchall():
        articles.append({
            "id":              row[0],
            "judul":           row[1] or "",
            "url":             row[2] or "",
            "summary":         row[3] or "",
            "published":       row[4] or "",
            "source_nama":     row[5] or "",
            "kompetitor":      row[6] or "",
            "full_content":    row[7] or "",
            "sentiment_label": row[8] or "neutral",
            "sentiment_score": row[9] or 0.0,
        })

    logger.info(f"Loaded {len(articles)} articles dari database")
    return articles


def build_chroma_index(
    articles: list[dict],
    embedding_model: SentenceTransformer,
    chroma_client: Any
) -> Any:
    """
    Build ChromaDB index dari artikel.
    Idempotent — aman dijalankan ulang.

    Metadata yang disimpan bersama vector:
    - article_id : untuk lookup ke SQLite
    - kompetitor : untuk filter saat retrieval
    - sentiment  : untuk context di LLM
    - published  : untuk time-based filtering
    - source     : untuk attribution di report
    """
    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
        # cosine similarity: scale-invariant
        # lebih robust dari euclidean untuk teks
    )

    # Cek artikel yang sudah ada di index
    existing = set()
    if collection.count() > 0:
        existing_data = collection.get()
        existing = set(existing_data["ids"])

    new_count = 0
    for article in articles:
        doc_id = f"article_{article['id']}"

        # Skip kalau sudah di-index — incremental update
        if doc_id in existing:
            continue

        # Buat teks untuk embedding
        text_for_embedding = clean_for_embedding(
            article["judul"],
            article["summary"],
            article["full_content"]
        )

        if len(text_for_embedding) < 10:
            logger.warning(
                f"Skip article {article['id']} — "
                f"text terlalu pendek untuk di-index"
            )
            continue

        # Generate embedding
        embedding = embedding_model.encode(
            text_for_embedding,
            normalize_embeddings=True
            # normalize: pastikan cosine similarity bekerja benar
        ).tolist()

        # Simpan ke ChromaDB dengan metadata
        collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text_for_embedding],
            metadatas=[{
                "article_id":      article["id"],
                "kompetitor":      article["kompetitor"],
                "sentiment_label": article["sentiment_label"],
                "sentiment_score": float(article["sentiment_score"]),
                "published":       article["published"],
                "source_nama":     article["source_nama"],
                "judul":           article["judul"][:200],
            }]
        )
        new_count += 1

    logger.info(
        f"Index updated — {new_count} artikel baru, "
        f"{collection.count()} total di ChromaDB"
    )
    return collection


# ============================================================
# STEP 3 — RETRIEVAL PIPELINE
# ============================================================

def retrieve_relevant_articles(
    query: str,
    collection: Any,
    embedding_model: SentenceTransformer,
    conn: sqlite3.Connection,
    kompetitor_filter: Optional[str] = None,
    top_k: int = TOP_K
) -> list[dict]:
    """
    Retrieve artikel paling relevan dengan query menggunakan
    cosine similarity di ChromaDB.

    Flow:
    1. Embed query dengan model yang sama saat indexing
    2. Similarity search di ChromaDB
    3. Optional filter by kompetitor via metadata
    4. Enrich hasil dengan full_content dari SQLite
    """
    # Step 3a — embed query
    query_embedding = embedding_model.encode(
        query,
        normalize_embeddings=True
    ).tolist()

    # Step 3b — build filter
    where_filter = None
    if kompetitor_filter:
        where_filter = {"kompetitor": {"$eq": kompetitor_filter}}

    # Step 3c — similarity search
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        where=where_filter,
        include=["metadatas", "distances", "documents"]
    )

    if not results or not results["ids"][0]:
        logger.warning("Tidak ada artikel yang diretrieve")
        return []

    # Step 3d — enrich dengan full_content dari SQLite
    # ChromaDB hanya simpan metadata ringkas
    # Full content tetap di SQLite untuk efisiensi storage
    enriched = []
    cursor = conn.cursor()

    for i, doc_id in enumerate(results["ids"][0]):
        metadata  = results["metadatas"][0][i]
        distance  = results["distances"][0][i]
        article_id = metadata["article_id"]

        # Ambil full_content dari SQLite
        cursor.execute("""
            SELECT ac.full_content
            FROM article_contents ac
            WHERE ac.article_id = ?
        """, (article_id,))
        row = cursor.fetchone()
        full_content = row[0] if row else ""

        enriched.append({
            "article_id":      article_id,
            "judul":           metadata.get("judul", ""),
            "kompetitor":      metadata.get("kompetitor", ""),
            "sentiment_label": metadata.get("sentiment_label", "neutral"),
            "sentiment_score": metadata.get("sentiment_score", 0.0),
            "published":       metadata.get("published", ""),
            "source_nama":     metadata.get("source_nama", ""),
            "similarity":      round(1 - distance, 3),
            "full_content":    full_content,
        })

    logger.info(
        f"Retrieved {len(enriched)} artikel "
        f"(query='{query[:50]}', "
        f"filter={kompetitor_filter})"
    )
    return enriched


def build_context_block(articles: list[dict]) -> str:
    """
    Gabungkan artikel yang diretrieve menjadi satu context block
    untuk dikirim ke LLM.

    Format yang jelas membantu LLM memahami struktur data
    dan menghasilkan output yang lebih akurat.
    """
    if not articles:
        return "Tidak ada artikel yang relevan ditemukan."

    blocks = []
    for i, article in enumerate(articles, 1):
        text = clean_for_llm(
            article["judul"],
            None,
            article["full_content"]
        )

        block = f"""
[Artikel {i}]
Kompetitor : {article['kompetitor']}
Sentimen   : {article['sentiment_label']} ({article['sentiment_score']:.2f})
Tanggal    : {article['published'][:10] if article['published'] else 'N/A'}
Sumber     : {article['source_nama']}
Similarity : {article['similarity']}
---
{text}
""".strip()
        blocks.append(block)

    return "\n\n".join(blocks)

# ============================================================
# STEP 4 — GENERATION PIPELINE
# ============================================================

SYSTEM_PROMPT = """
Kamu adalah analis competitive intelligence senior untuk Telkom Indonesia,
khusus fokus pada produk Indibiz (B2B enterprise).

Tugasmu adalah menganalisis berita kompetitor dan menghasilkan insight
yang actionable untuk tim Indibiz.

Ketika menganalisis, selalu pertimbangkan:
1. Dampak langsung terhadap segmen B2B/enterprise Indibiz
2. Ancaman konkret yang perlu diantisipasi
3. Peluang yang bisa dimanfaatkan Telkom/Indibiz
4. Konteks regulasi telekomunikasi Indonesia

Aturan penting:
- Hanya gunakan informasi dari artikel yang diberikan
- Jangan tambahkan fakta yang tidak ada di artikel
- Gunakan Bahasa Indonesia yang profesional
- Format output selalu dalam JSON yang valid
"""

REPORT_SCHEMA = """
Return ONLY valid JSON dengan format berikut, tanpa markdown atau teks lain:
{
  "executive_summary": "ringkasan 2-3 kalimat tentang situasi kompetitor",
  "key_events": [
    {
      "kompetitor": "nama kompetitor",
      "event": "deskripsi singkat kejadian",
      "dampak": "positive/negative/neutral untuk Indibiz",
      "urgensi": "tinggi/sedang/rendah"
    }
  ],
  "ancaman_indibiz": [
    "ancaman spesifik 1",
    "ancaman spesifik 2"
  ],
  "peluang_indibiz": [
    "peluang spesifik 1",
    "peluang spesifik 2"
  ],
  "rekomendasi_aksi": [
    {
      "aksi": "deskripsi aksi yang direkomendasikan",
      "prioritas": "tinggi/sedang/rendah",
      "timeline": "segera/minggu ini/bulan ini"
    }
  ],
  "artikel_count": 0,
  "generated_at": "ISO timestamp"
}
"""


def generate_intelligence_report(
    context: str,
    gemini_model: Any,
    query: str = "analisis kompetitor telco Indonesia"
) -> dict:
    """
    Generate structured intelligence report menggunakan Gemini.

    Menggunakan structured output (JSON) bukan free-form text karena:
    - Output predictable dan parseable
    - Bisa langsung masuk ke database
    - Konsisten setiap run
    - Dashboard-ready
    """
    prompt = f"""
Berdasarkan artikel-artikel berikut tentang kompetitor telekomunikasi Indonesia,
buat laporan competitive intelligence untuk tim Indibiz.

Query fokus: {query}

=== ARTIKEL ===
{context}

=== INSTRUKSI OUTPUT ===
{REPORT_SCHEMA}
"""

    try:
        response = gemini_model.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=8192,
            )
        )
        raw_text = response.text.strip()

        # Clean markdown kalau ada
        if raw_text.startswith("```"):
            raw_text = re.sub(r'```json\n?|```\n?', '', raw_text).strip()

        report = json.loads(raw_text)

        # Tambahkan metadata
        report["generated_at"] = datetime.now(timezone.utc).isoformat()
        report["artikel_count"] = context.count("[Artikel")

        return report

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini response as JSON: {e}")
        logger.error(f"Raw response: {response.text[:500]}")
        return {
            "error": "Failed to parse response",
            "raw_response": response.text[:1000],
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        return {
            "error": str(e),
            "generated_at": datetime.now(timezone.utc).isoformat()
        }


def save_report(
    conn: sqlite3.Connection,
    report: dict,
    query: str,
    kompetitor_filter: Optional[str]
) -> Optional[int]:
    """
    Simpan intelligence report ke database.
    Sehingga tidak perlu re-generate setiap kali — hemat API calls.
    """
    cursor = conn.cursor()

    # Buat table kalau belum ada
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS intelligence_reports (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            query             TEXT,
            kompetitor_filter TEXT,
            report_json       TEXT NOT NULL,
            generated_at      TEXT NOT NULL,
            model_used        TEXT DEFAULT 'gemini-1.5-flash'
        )
    """)

    cursor.execute("""
        INSERT INTO intelligence_reports
        (query, kompetitor_filter, report_json, generated_at, model_used)
        VALUES (?, ?, ?, ?, ?)
    """, (
        query,
        kompetitor_filter,
        json.dumps(report, ensure_ascii=False),
        datetime.now(timezone.utc).isoformat(),
        GEMINI_MODEL
    ))

    conn.commit()
    report_id = cursor.lastrowid
    logger.info(f"Report saved — id={report_id}")
    return report_id

# ============================================================
# STEP 5 — MAIN PIPELINE
# ============================================================

def init_services() -> tuple:
    """
    Initialize semua services yang dibutuhkan.
    Load sekali, pakai berkali-kali — tidak re-load setiap request.
    """
    # Load embedding model
    logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
    embedding_model = SentenceTransformer(EMBEDDING_MODEL)
    logger.info("Embedding model loaded.")

    # Init ChromaDB
    logger.info(f"Initializing ChromaDB at: {CHROMA_PATH}")
    Path(CHROMA_PATH).mkdir(parents=True, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
    logger.info("ChromaDB initialized.")

    # Init Gemini
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY tidak ditemukan di .env. "
            "Buat API key di https://aistudio.google.com/apikey"
        )
    gemini_model = genai.Client(api_key=api_key)
    logger.info(f"Gemini model initialized: {GEMINI_MODEL}")

    return embedding_model, chroma_client, gemini_model


def run_indexing() -> None:
    """
    Jalankan indexing pipeline — build ChromaDB dari articles.db.
    Aman dijalankan ulang — incremental update.
    """
    logger.info("=" * 50)
    logger.info("INDEXING PIPELINE")
    logger.info("=" * 50)

    embedding_model, chroma_client, _ = init_services()
    conn = sqlite3.connect(DB_PATH)

    articles   = load_articles_from_db(conn)
    collection = build_chroma_index(
        articles, embedding_model, chroma_client
    )

    logger.info(
        f"Indexing complete — "
        f"{collection.count()} artikel di ChromaDB"
    )
    conn.close()


def run_daily_digest(
    kompetitor_filter: Optional[str] = None
) -> dict:
    """
    Generate daily competitive intelligence digest.
    Query default mencakup semua kompetitor kecuali ada filter.
    """
    logger.info("=" * 50)
    logger.info("DAILY DIGEST PIPELINE")
    logger.info("=" * 50)

    embedding_model, chroma_client, gemini_model = init_services()
    conn = sqlite3.connect(DB_PATH)

    # Get atau buat collection
    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )

    if collection.count() == 0:
        logger.warning(
            "ChromaDB kosong — jalankan indexing dulu: "
            "python -m src.intelligence.rag_pipeline index"
        )
        conn.close()
        return {"error": "index_empty"}

    # Build query berdasarkan filter
    if kompetitor_filter:
        query = (
            f"perkembangan terbaru {kompetitor_filter} "
            f"produk layanan strategi bisnis Indonesia"
        )
    else:
        query = (
            "perkembangan kompetitor telekomunikasi Indonesia "
            "Telkomsel Indosat XL Axiata strategi produk layanan"
        )

    # Retrieve artikel relevan
    articles = retrieve_relevant_articles(
        query=query,
        collection=collection,
        embedding_model=embedding_model,
        conn=conn,
        kompetitor_filter=kompetitor_filter,
        top_k=TOP_K
    )

    if not articles:
        logger.warning("Tidak ada artikel untuk di-analyze")
        conn.close()
        return {"error": "no_articles"}

    # Build context untuk LLM
    context = build_context_block(articles)
    logger.info(
        f"Context built — {len(articles)} artikel, "
        f"{len(context)} chars"
    )

    # Generate report
    report = generate_intelligence_report(
        context=context,
        gemini_model=gemini_model,
        query=query
    )

    # Save ke database
    if "error" not in report:
        save_report(conn, report, query, kompetitor_filter)

    conn.close()
    return report


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    import sys

    command = sys.argv[1] if len(sys.argv) > 1 else "digest"

    if command == "index":
        run_indexing()

    elif command == "digest":
        kompetitor = sys.argv[2] if len(sys.argv) > 2 else None
        report     = run_daily_digest(kompetitor)

        print("\n=== INTELLIGENCE REPORT ===")
        if "error" in report:
            print(f"Error: {report['error']}")
        else:
            print(f"\nExecutive Summary:")
            print(f"  {report.get('executive_summary', 'N/A')}")

            print(f"\nKey Events ({len(report.get('key_events', []))}):")
            for event in report.get("key_events", []):
                print(
                    f"  [{event.get('urgensi','?').upper()}] "
                    f"{event.get('kompetitor','?')}: "
                    f"{event.get('event','?')}"
                )

            print(f"\nAncaman Indibiz:")
            for ancaman in report.get("ancaman_indibiz", []):
                print(f"  ⚠️  {ancaman}")

            print(f"\nPeluang Indibiz:")
            for peluang in report.get("peluang_indibiz", []):
                print(f"  ✅ {peluang}")

            print(f"\nRekomendasi:")
            for rec in report.get("rekomendasi_aksi", []):
                print(
                    f"  [{rec.get('prioritas','?').upper()}] "
                    f"{rec.get('aksi','?')} "
                    f"→ {rec.get('timeline','?')}"
                )

    elif command == "query":
        if len(sys.argv) < 3:
            print("Usage: python -m src.intelligence.rag_pipeline query <pertanyaan>")
            sys.exit(1)

        query      = " ".join(sys.argv[2:])
        embedding_model, chroma_client, gemini_model = init_services()
        conn       = sqlite3.connect(DB_PATH)
        collection = chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )

        articles = retrieve_relevant_articles(
            query=query,
            collection=collection,
            embedding_model=embedding_model,
            conn=conn,
        )
        context = build_context_block(articles)
        report  = generate_intelligence_report(
            context=context,
            gemini_model=gemini_model,
            query=query
        )

        print(json.dumps(report, ensure_ascii=False, indent=2))
        conn.close()

    else:
        print("Commands: index | digest [kompetitor] | query <pertanyaan>")