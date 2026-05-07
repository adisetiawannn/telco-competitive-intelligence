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
    artikel_relevan = "XL Axiata meluncurkan paket enterprise baru"
    artikel_tidak_relevan = "Pemerintah umumkan kebijakan pertanian"
    
    assert is_artikel_relevan(artikel_relevan) == True
    assert is_artikel_relevan(artikel_tidak_relevan) == False