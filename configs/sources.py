# data class source
from dataclasses import dataclass
from typing import List, Optional

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
class KompetitorConfig :
    """
    Konfigurasi untuk satu kompetitor yang dipantau.
    Berisi keyword yang digunakan untuk filter artikel relevan.
    """
    nama : str
    keywords : List[str]
    segmen : str  # 'b2b', 'b2c', atau 'both'

# ============================================================
# COMPETITOR CONFIGURATION
# ============================================================

KOMPETITOR = [
    KompetitorConfig(
        nama="telkom",
        keywords=["telkom", "telkom indonesia", "Telkom", "PT Telkomunikasi Indonesia"],
        segmen="both"
    ),
    KompetitorConfig(
        nama="Telkomsel",
        keywords=["telkomsel", "tsel", "indihome", "by.u"],
        segmen="both"
    ),
    KompetitorConfig(
        nama="XL Axiata",
        keywords=["xl axiata", "xl home", "axis", "xlink"],
        segmen="both"
    ),
    KompetitorConfig(
        nama="Indosat",
        keywords=["indosat", "im3", "ooredoo", "indosat ooredoo"],
        segmen="both"
    ),
    KompetitorConfig(
        nama="Biznet",
        keywords=["biznet", "biznet networks", "biznet metro"],
        segmen="both"
    ),
    KompetitorConfig(
        nama="MyRepublic",
        keywords=["myrepublic", "my republic","my-republic", "my republic indonesia","myrep"],
        segmen="both"
    ),
    KompetitorConfig(
        nama="Icon+",
        keywords=["icon+", "iconplus", "icon plus"],
        segmen="both"
    ),
    KompetitorConfig(
    nama="General Telco",
    keywords=[
        "telekomunikasi", "operator seluler", "provider internet",
        "layanan internet", "fixed broadband", "fiber optik", 
        "5g indonesia", "indibiz",
        "telkom indonesia", "tlkm","isat","excl"
    ],
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
    """Return semua keywords dari semua kompetitor."""
    keywords = []
    for k in KOMPETITOR:
        keywords.extend(k.keywords)
    return keywords


def is_artikel_relevan(teks: str) -> bool:
    """
    Check apakah sebuah artikel relevan dengan kompetitor yang dipantau.
    Case-insensitive matching.
    """
    teks_lower = teks.lower()
    return any(keyword in teks_lower for keyword in get_all_keywords())