# tests/test_sources.py

from configs.sources import (
    get_active_sources,
    get_all_keywords,
    is_artikel_relevan
)


def test_active_sources():
    sources = get_active_sources()
    assert len(sources) > 0, "Harus ada minimal 1 active source"
    for s in sources:
        assert s.aktif == True


def test_all_keywords():
    keywords = get_all_keywords()
    assert len(keywords) > 0, "Harus ada minimal 1 keyword"
    assert "telkomsel" in keywords
    assert "biznet" in keywords


def test_artikel_relevan():
    # Brand di judul — harus relevan
    assert is_artikel_relevan(
        "XL Axiata meluncurkan paket enterprise baru"
    ) == True

    # Tidak ada keyword sama sekali — harus ditolak
    assert is_artikel_relevan(
        "Pemerintah umumkan kebijakan pertanian"
    ) == False

    # Industry keyword di judul — cukup untuk lolos
    assert is_artikel_relevan(
        "Lelang frekuensi 700 MHz akan segera dimulai"
    ) == True

    # Brand di summary — harus relevan
    assert is_artikel_relevan(
        "Bisnis Q1 2026 tumbuh signifikan",
        "Indosat Ooredoo mencatat pertumbuhan pelanggan baru"
    ) == True

    # Regression test — artikel judol yang pernah lolos filter
    assert is_artikel_relevan(
        "321 WNA Sindikat Judol di Jakbar Pakai Visa Wisata"
    ) == False