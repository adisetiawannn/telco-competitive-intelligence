# scripts/discover_rss.py

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from src.ingestion.rss_discovery import RSSDiscovery

TARGET_SITES = {
    "detik":      "https://www.detik.com",
    "kompas":     "https://www.kompas.com",
    "kontan":     "https://www.kontan.co.id",
    "bisnis":     "https://bisnis.com",
    "katadata":   "https://katadata.co.id",
    "cnbc_id":    "https://www.cnbcindonesia.com",
    "techinasia": "https://www.techinasia.com",
}

discovery = RSSDiscovery()
feeds = discovery.run_full_discovery(TARGET_SITES)

# FIX — gunakan .get() bukan [] agar tidak KeyError
print("\n=== HASIL DISCOVERY ===")
for name, info in sorted(
    feeds.items(),
    key=lambda x: x[1].get("quality_score", 0)   # ← .get() dengan default 0
        if isinstance(x[1], dict) else 0,
    reverse=True
):
    if isinstance(info, dict):
        score   = info.get("quality_score", 0)
        entries = info.get("entry_count", "-")
        url     = info.get("url", "")
        print(f"  {score:3}pts | {str(entries):>4} entries "
              f"| {name:<35} | {url}")