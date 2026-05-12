# src/ingestion/nlp_processor.py
"""
NLP Processor — Phase 2 Core
Menganalisis full content artikel dan menghasilkan:
- sentiment per artikel (nlp_results)
- competitor mentions dengan sentiment (competitor_mentions)
- daily aggregated stats (competitor_daily_stats)
"""

import re
import json
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Optional

from transformers import pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import LatentDirichletAllocation

from configs.sources import KOMPETITOR, keyword_match

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS
# ============================================================

DB_PATH       = "data/articles.db"
MODEL_VERSION = "v1.0"
MODEL_NAME    = "models/sentiment_v2/final" # path model IndoBERT yang sudah di-fine-tune
MODEL_VERSION = "v2.0" # update version kalau ada perubahan signifikan di model atau preprocessing

MAX_TOKEN_LENGTH = 512
MIN_CONTENT_NLP  = 100
N_TOPICS         = 5
N_KEYWORDS       = 10

SENTIMENT_MAP = {
    "positive": 1.0,
    "neutral":  0.0,
    "negative": -1.0,
}

# ============================================================
# DOMAIN SIGNAL RULES — telco-specific post-processing
# Override model output untuk kasus yang model masih salah.
# Log setiap override untuk tracking di v3.0.
# ============================================================

NEGATIVE_SIGNALS = [
    "gangguan", "rugi", "merugi", "kerugian",
    "turun", "anjlok", "masalah", "gagal",
    "complaint", "keluhan", "lambat", "lemot",
    "padam", "mati", "down", "error",
    "denda", "sanksi", "pelanggaran",
    "phk", "pemecatan", "bangkrut",
]

POSITIVE_SIGNALS = [
    "luncurkan", "meluncurkan", "hadirkan",
    "tumbuh", "naik", "capai", "raih",
    "ekspansi", "inovasi", "breakthrough",
    "tercepat", "terluas", "terbesar",
    "award", "penghargaan", "juara",
    "investasi", "kerjasama", "partnership",
    "profit", "untung", "pendapatan naik",
]


# ============================================================
# MODEL LOADER
# ============================================================

def load_sentiment_model():
    """Load IndoBERT sentiment model — hanya sekali saat startup."""
    logger.info(f"Loading sentiment model: {MODEL_NAME}")
    model = pipeline(
        "text-classification",
        model=MODEL_NAME,
        truncation=True,
        max_length=MAX_TOKEN_LENGTH
    )
    logger.info("Model loaded.")
    return model


# ============================================================
# TEXT PREPROCESSING
# ============================================================

def clean_text(text: Optional[str]) -> str:
    """
    Bersihkan teks dari noise sebelum NLP processing.
    Berbeda dari HTML cleaning di content_fetcher —
    ini fokus pada normalisasi linguistik.
    """
    if not text:
        return ""

    # Hapus URL
    text = re.sub(r'http\S+|www\S+', '', text)

    # Hapus karakter non-alfanumerik kecuali spasi dan tanda baca dasar
    text = re.sub(r'[^\w\s.,!?]', ' ', text)

    # Normalisasi whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def truncate_for_model(text: str, max_chars: int = 1500) -> str:
    """
    Truncate teks untuk model — BERT max 512 tokens.
    1500 chars ≈ 400-450 tokens untuk Bahasa Indonesia.
    """
    return text[:max_chars] if len(text) > max_chars else text


# ============================================================
# SENTIMENT ANALYSIS
# ============================================================

def analyze_sentiment(
    model,
    text: str
) -> tuple[str, float, float]:
    """
    Analisis sentiment menggunakan IndoBERT.
    Return: (label, score, confidence)
    - label: positive/negative/neutral
    - score: -1.0 sampai 1.0
    - confidence: 0.0 sampai 1.0
    """
    if not text or len(text) < MIN_CONTENT_NLP:
        return "neutral", 0.0, 0.0

    cleaned = clean_text(truncate_for_model(text))

    try:
        result    = model(cleaned)[0]
        label     = result["label"].lower()
        confidence = result["score"]
        score     = SENTIMENT_MAP.get(label, 0.0)
        return label, score, confidence

    except Exception as e:
        logger.error(f"Sentiment analysis failed: {e}")
        return "neutral", 0.0, 0.0

# ============================================================
# RULE BASED SENTIMENT ANALYSIS
# ============================================================
def post_process_sentiment(
    text: str,
    model_label: str,
    model_score: float,
    model_confidence: float
) -> tuple[str, float, float]:
    """
    Rule-based post-processing untuk override model output.
    
    Dipakai karena model masih mengandalkan emotional cues dari
    SmSA training, bukan domain knowledge telco.
    
    Setiap override di-log untuk tracking improvement di v3.0.
    
    Return: (label, score, confidence)
    """
    text_lower = text.lower()

    # Check negative signals dulu — lebih kritikal untuk intelligence
    for signal in NEGATIVE_SIGNALS:
        if signal in text_lower:
            if model_label != "negative":
                logger.debug(
                    f"RULE_OVERRIDE: '{signal}' "
                    f"→ {model_label} overridden to negative"
                )
            return "negative", -1.0, 0.75

    # Check positive signals
    for signal in POSITIVE_SIGNALS:
        if signal in text_lower:
            if model_label != "positive":
                logger.debug(
                    f"RULE_OVERRIDE: '{signal}' "
                    f"→ {model_label} overridden to positive"
                )
            return "positive", 1.0, 0.75

    # Tidak ada signal — percaya model
    return model_label, model_score, model_confidence



# ============================================================
# KEYWORD EXTRACTION — TF-IDF
# ============================================================

def extract_keywords(
    texts: list[str],
    article_idx: int,
    n_keywords: int = N_KEYWORDS
) -> list[str]:
    """
    Extract top keywords dari satu artikel menggunakan TF-IDF.
    Butuh corpus (semua teks) untuk hitung IDF yang akurat.
    """
    if len(texts) < 2:
        return []

    try:
        vectorizer = TfidfVectorizer(
            max_features=1000,
            min_df=1,
            stop_words=None,      # kita handle stopwords sendiri
            ngram_range=(1, 2)    # unigram dan bigram
        )

        tfidf_matrix = vectorizer.fit_transform(texts)
        feature_names = vectorizer.get_feature_names_out().tolist()

        # Ambil score untuk artikel yang diminta
        if article_idx < 0 or article_idx >= tfidf_matrix.shape[0]:
            return []
        article_scores = tfidf_matrix.getrow(article_idx).toarray()[0]

        # Sort by score, ambil top N
        top_indices = article_scores.argsort()[-n_keywords:][::-1]
        keywords = [
            feature_names[i]
            for i in top_indices
            if article_scores[i] > 0
        ]

        return keywords

    except Exception as e:
        logger.error(f"Keyword extraction failed: {e}")
        return []


# ============================================================
# TOPIC MODELING — LDA
# ============================================================

def extract_topics(
    texts: list[str],
    n_topics: int = N_TOPICS,
    n_words: int = 5
) -> list[list[str]]:
    """
    Ekstrak topics dari corpus menggunakan LDA.
    Return: list of topics, masing-masing berisi top words.
    """
    if len(texts) < n_topics:
        return []

    try:
        vectorizer = TfidfVectorizer(
            max_features=500,
            min_df=2,
            ngram_range=(1, 1)
        )

        tfidf_matrix = vectorizer.fit_transform(texts)
        feature_names = vectorizer.get_feature_names_out()

        lda = LatentDirichletAllocation(
            n_components=n_topics,
            random_state=42,
            max_iter=20
        )
        lda.fit(tfidf_matrix)

        topics = []
        for topic in lda.components_:
            top_indices = topic.argsort()[-n_words:][::-1]
            top_words   = [feature_names[i] for i in top_indices]
            topics.append(top_words)

        return topics

    except Exception as e:
        logger.error(f"Topic modeling failed: {e}")
        return []


# ============================================================
# COMPETITOR DETECTION
# ============================================================

def detect_competitor_mentions(
    text: str,
    sentiment_score: float
) -> list[dict]:
    """
    Deteksi mention kompetitor dalam teks.
    Gunakan word boundary matching dari configs.sources.
    Return: list of {competitor, mention_count, sentiment_score}
    """
    mentions = []
    text_lower = text.lower()

    for kompetitor in KOMPETITOR:
        if kompetitor.nama == "General Telco":
            continue

        count = 0
        for kw in kompetitor.brand_keywords + kompetitor.keywords:
            pattern = r'\b' + re.escape(kw.lower()) + r'\b'
            matches = re.findall(pattern, text_lower)
            count  += len(matches)

        if count > 0:
            mentions.append({
                "competitor":      kompetitor.nama,
                "mention_count":   count,
                "sentiment_score": sentiment_score
            })

    return mentions


# ============================================================
# DATABASE HELPERS
# ============================================================

def get_articles_for_nlp(conn: sqlite3.Connection) -> list:
    """Ambil artikel yang sudah di-fetch tapi belum di-NLP."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            a.id,
            a.judul,
            a.published,
            a.source_nama,
            ac.full_content
        FROM articles a
        JOIN article_contents ac ON a.id = ac.article_id
        WHERE a.content_fetched = 1
          AND a.nlp_processed  = 0
        ORDER BY a.published DESC
    """)
    return cursor.fetchall()


def save_nlp_result(
    conn: sqlite3.Connection,
    article_id: int,
    sentiment_label: str,
    sentiment_score: float,
    sentiment_confidence: float,
    topics: list,
    keywords: list
) -> None:
    """Simpan hasil NLP ke table nlp_results."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO nlp_results
        (article_id, sentiment_label, sentiment_score,
         sentiment_confidence, topics, keywords,
         processed_at, model_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        article_id,
        sentiment_label,
        sentiment_score,
        sentiment_confidence,
        json.dumps(topics,    ensure_ascii=False),
        json.dumps(keywords,  ensure_ascii=False),
        datetime.now(timezone.utc).isoformat(),
        MODEL_VERSION
    ))

    cursor.execute("""
        UPDATE articles
        SET nlp_processed = 1
        WHERE id = ?
    """, (article_id,))

    conn.commit()


def save_competitor_mentions(
    conn: sqlite3.Connection,
    article_id: int,
    mentions: list[dict]
) -> None:
    """Simpan competitor mentions ke table."""
    cursor = conn.cursor()
    for mention in mentions:
        cursor.execute("""
            INSERT OR REPLACE INTO competitor_mentions
            (article_id, competitor, mention_count, sentiment_score)
            VALUES (?, ?, ?, ?)
        """, (
            article_id,
            mention["competitor"],
            mention["mention_count"],
            mention["sentiment_score"]
        ))
    conn.commit()


def update_daily_stats(conn: sqlite3.Connection) -> None:
    """
    Recompute competitor_daily_stats dari competitor_mentions.
    Pakai INSERT OR REPLACE — idempotent, aman dijalankan ulang.
    """
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR REPLACE INTO competitor_daily_stats
        (competitor, date, mention_count,
         positive_count, negative_count, neutral_count,
         avg_sentiment, share_of_voice)

        SELECT
            cm.competitor,
            DATE(a.published)                          AS date,
            COUNT(*)                                   AS mention_count,
            SUM(CASE WHEN nr.sentiment_label = 'positive' THEN 1 ELSE 0 END),
            SUM(CASE WHEN nr.sentiment_label = 'negative' THEN 1 ELSE 0 END),
            SUM(CASE WHEN nr.sentiment_label = 'neutral'  THEN 1 ELSE 0 END),
            AVG(cm.sentiment_score),
            0.0
        FROM competitor_mentions cm
        JOIN articles   a  ON cm.article_id = a.id
        JOIN nlp_results nr ON cm.article_id = nr.article_id
        WHERE DATE(a.published) IS NOT NULL
        GROUP BY cm.competitor, DATE(a.published)
    """)

    # Update share_of_voice — persen mention per kompetitor per hari
    cursor.execute("""
        UPDATE competitor_daily_stats AS cds
        SET share_of_voice = (
            SELECT ROUND(
                cds.mention_count * 100.0 /
                SUM(inner_cds.mention_count), 2
            )
            FROM competitor_daily_stats inner_cds
            WHERE inner_cds.date = cds.date
        )
    """)

    conn.commit()
    logger.info("Daily stats updated.")


# ============================================================
# MAIN PIPELINE
# ============================================================

def run_nlp() -> dict:
    """
    Main NLP pipeline:
    1. Load model
    2. Fetch articles yang belum di-NLP
    3. Sentiment analysis per artikel
    4. Keyword extraction (TF-IDF atas corpus)
    5. Topic modeling (LDA atas corpus)
    6. Competitor mention detection
    7. Update daily stats
    """
    stats = {
        "total_pending":   0,
        "total_processed": 0,
        "total_failed":    0,
    }

    model = load_sentiment_model()
    conn  = sqlite3.connect(DB_PATH)

    articles = get_articles_for_nlp(conn)
    stats["total_pending"] = len(articles)

    if not articles:
        logger.info("Tidak ada artikel pending untuk NLP.")
        conn.close()
        return stats

    logger.info(f"Memproses {len(articles)} artikel...")

    # Siapkan corpus untuk TF-IDF dan LDA
    corpus = [
        clean_text(row[4])      # full_content
        for row in articles
    ]

    # Topic modeling di level corpus — satu kali untuk semua artikel
    topics_corpus = extract_topics(corpus)
    logger.info(f"Topics extracted: {len(topics_corpus)} topics")

    for idx, (article_id, judul, published, source, content) in enumerate(articles):
        logger.info(f"[{idx+1}/{len(articles)}] {judul[:60]}...")

        try:
            # 1. Sentiment — model prediction
            raw_label, raw_score, raw_confidence = analyze_sentiment(
                model, content
            )

            # 1b. Post-processing — rule-based override untuk domain telco
            label, score, confidence = post_process_sentiment(
                judul + " " + (content[:500] if content else ""),
                raw_label, raw_score, raw_confidence
            )

            # 2. Keywords per artikel
            keywords = extract_keywords(corpus, idx)

            # 3. Assign topics — ambil top topic untuk artikel ini
            article_topics = [
                topics_corpus[i]
                for i in range(len(topics_corpus))
            ] if topics_corpus else []

            # 4. Save nlp_results
            save_nlp_result(
                conn, article_id,
                label, score, confidence,
                article_topics, keywords
            )

            # 5. Competitor mentions
            mentions = detect_competitor_mentions(content, score)
            if mentions:
                save_competitor_mentions(conn, article_id, mentions)
                logger.info(
                    f"  → {label} ({score:.2f}) | "
                    f"{len(mentions)} competitor mentions"
                )
            else:
                logger.info(f"  → {label} ({score:.2f}) | no mentions")

            stats["total_processed"] += 1

        except Exception as e:
            logger.error(f"  → Failed: {e}")
            stats["total_failed"] += 1

    # 6. Update daily stats setelah semua artikel diproses
    update_daily_stats(conn)
    conn.close()

    logger.info(f"NLP complete: {stats}")
    return stats


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    stats = run_nlp()

    print("\n=== NLP SUMMARY ===")
    print(f"  Total pending   : {stats['total_pending']}")
    print(f"  Processed       : {stats['total_processed']}")
    print(f"  Failed          : {stats['total_failed']}")