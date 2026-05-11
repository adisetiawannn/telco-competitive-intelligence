# data class source

from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, field

# tambahkan di bagian import atas
import yaml
import logging

logger = logging.getLogger(__name__)

# ============================================================
# DATA STRUCTURE DEFINITION
# ============================================================
@dataclass
class NewsSource:
    """
    Representasi satu sumber berita yang akan dipantau.
    Menggunakan dataclass untuk type safety dan self-documentation.
    """
    nama : str
    url : str
    kompetitor : str
    kategori : str
    aktif : bool = True
    bahasa : Optional[str] = None


@dataclass
class KompetitorConfig:
    nama:           str
    keywords:       List[str]
    segmen:         str
    brand_keywords: List[str] = field(default_factory=list)
    # brand_keywords = keyword high-confidence yang identik dengan brand
    # jika kosong, pakai keywords sebagai fallback


KOMPETITOR = [
    KompetitorConfig(
        nama="telkom",
        keywords=["telkom", "telkom indonesia", "telkom group", "tlkm"],
        brand_keywords=["telkom indonesia", "pt telkom", "telkom group"],
        segmen="both"
    ),
    KompetitorConfig(
        nama="Telkomsel",
        keywords=["telkomsel", "tsel", "indihome", "by.u", "digiland"],
        brand_keywords=["telkomsel", "indihome", "by.u"],
        segmen="both"
    ),
    KompetitorConfig(
        nama="XL Axiata",
        keywords=["xl axiata", "xl home", "axis", "xlink", "excl"],
        brand_keywords=["xl axiata", "xl home", "axis telecom"],
        segmen="both"
    ),
    KompetitorConfig(
        nama="Indosat",
        keywords=["indosat", "im3", "ooredoo", "isat"],
        brand_keywords=["indosat", "im3 ooredoo", "indosat ooredoo"],
        segmen="both"
    ),
    KompetitorConfig(
        nama="Biznet",
        keywords=["biznet", "biznet networks", "biznet metro"],
        brand_keywords=["biznet", "biznet networks"],
        segmen="both"
    ),
    KompetitorConfig(
        nama="MyRepublic",
        keywords=["myrepublic", "my republic"],
        brand_keywords=["myrepublic", "my republic indonesia"],
        segmen="both"
    ),
    KompetitorConfig(
        nama="Icon+",
        keywords=["icon+", "iconplus", "icon plus"],
        brand_keywords=["icon+", "iconplus"],
        segmen="both"
    ),
    KompetitorConfig(
        nama="General Telco",
        # Industry keywords — low confidence, tidak cukup sendirian
        keywords=[
            "operator seluler", "provider internet",
            "fixed broadband", "fiber optik",
            "5g indonesia", "indibiz", "frekuensi 700",
            "spektrum frekuensi", "lelang frekuensi"
        ],
        brand_keywords=[],  # tidak ada brand spesifik
        segmen="both"
    ),
]

# ============================================================
# RSS FEED SOURCES
# ============================================================

SOURCES = [
    NewsSource(
        nama="Detik Inet",
        url="https://inet.detik.com/rss",
        kompetitor="general",
        kategori="teknologi",
        bahasa="indonesia"
    ),
    NewsSource(
        nama="CNBC Indonesia Tech",
        url="https://www.cnbcindonesia.com/tech/rss",
        kompetitor="general",
        kategori="bisnis_teknologi",
        bahasa="indonesia"
    ),
    NewsSource(
        nama="CNN Indonesia Technology",
        url="https://www.cnnindonesia.com/teknologi/rss",
        kompetitor="general",
        kategori="bisnis_teknologi",
        bahasa="indonesia"
    ),
    NewsSource(
        nama="tirto id",
        url="https://tirto.id/sitemap/r/google-discover",
        kompetitor="general",
        kategori="general",
        bahasa="indonesia"
    ),
    NewsSource(
        nama="Telko ID",
        url="https://telko.id/feed",
        kompetitor="general",
        kategori="telko_spesifik",
        bahasa="indonesia"
    ),
    NewsSource(
        nama="Selular ID",
        url="https://selular.id/feed",
        kompetitor="general",
        kategori="telko_spesifik",
        bahasa="indonesia"
    ),    
]

# ============================================================
# HELPER FUNCTIONS
# ============================================================
def get_active_sources() -> List[NewsSource]:
    """Return hanya sources yang aktif."""
    return [s for s in SOURCES if s.aktif]

def get_all_keywords() -> List[str]:
    result = []
    for k in KOMPETITOR:
        result.extend(k.keywords)
    return list(set(result))


def get_brand_keywords() -> List[str]:
    result = []
    for k in KOMPETITOR:
        result.extend(k.brand_keywords)
    return list(set(result))


def hitung_relevansi_score(judul: str, summary: str) -> int:
    """
    Scoring system untuk relevansi artikel.
    Return integer score — makin tinggi makin relevan.

    Scoring rules:
    - Brand keyword di judul     : 3 poin
    - Brand keyword di summary   : 2 poin
    - Industry keyword di judul  : 2 poin
    - Industry keyword di summary: 1 poin
    """
    score = 0
    judul_lower   = judul.lower()
    summary_lower = summary.lower() if summary else ""

    for kompetitor in KOMPETITOR:
        is_general = kompetitor.nama == "General Telco"

        # Brand keywords — high confidence
        for kw in kompetitor.brand_keywords:
            kw_lower = kw.lower()
            if kw_lower in judul_lower:
                score += 3
            elif kw_lower in summary_lower:
                score += 2

        # Non-general: regular keywords juga contributes
        if not is_general:
            for kw in kompetitor.keywords:
                kw_lower = kw.lower()
                # Hindari double-count kalau sudah di brand_keywords
                if kw_lower in kompetitor.brand_keywords:
                    continue
                if kw_lower in judul_lower:
                    score += 2
                elif kw_lower in summary_lower:
                    score += 1

        # General Telco keywords — low confidence
        if is_general:
            for kw in kompetitor.keywords:
                kw_lower = kw.lower()
                if kw_lower in judul_lower:
                    score += 2
                elif kw_lower in summary_lower:
                    score += 1

    return score


RELEVANSI_THRESHOLD = 2  # minimum score untuk dianggap relevan


def is_artikel_relevan(judul: str, summary: str = "") -> bool:
    """
    Check relevansi dengan scoring system.
    Lebih akurat dari simple keyword matching.
    """
    score = hitung_relevansi_score(judul, summary)
    return score >= RELEVANSI_THRESHOLD

# ============================================================
# LOAD YAML FILE
# ============================================================

def load_sources_from_yaml(
    yaml_path: str = "configs/rss_feeds.yaml"
) -> List[NewsSource]:
    """
    Load RSS sources dari YAML file hasil rss_discovery.
    Fallback ke hardcoded SOURCES kalau YAML tidak ditemukan.
    """
    yaml_file = Path(yaml_path)

    if not yaml_file.exists():
        logger.warning(
            f"YAML tidak ditemukan di {yaml_path}, "
            f"menggunakan hardcoded sources sebagai fallback."
        )
        return SOURCES

    with open(yaml_file, "r", encoding="utf-8") as f:
        feeds = yaml.safe_load(f)

    if not feeds:
        logger.warning("YAML kosong, menggunakan hardcoded sources.")
        return SOURCES

    sources = []
    for key, info in feeds.items():
        # Skip entry yang tidak valid
        if not isinstance(info, dict) or "url" not in info:
            continue

        sources.append(NewsSource(
            nama=info.get("title", key),
            url=info["url"],
            kompetitor=info.get("keyword", "general"),
            kategori=info.get("category", "umum"),
            aktif=True
        ))

    logger.info(f"Loaded {len(sources)} sources dari {yaml_path}")
    return sources