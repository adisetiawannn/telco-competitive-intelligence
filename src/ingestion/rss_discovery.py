# src/ingestion/rss_discovery.py

import logging
import requests
import feedparser
import yaml
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, quote
from pathlib import Path

logger = logging.getLogger(__name__)


class RSSDiscovery:

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
    }

    COMMON_PATHS = [
        "/rss", "/rss/", "/rss.xml",
        "/atom.xml", "/feed.xml", "/feeds/rss",
        "/index.xml",
        "/ekonomi/rss", "/teknologi/rss", "/bisnis/rss",
        "/tech/rss", "/telekomunikasi/rss", "/industri/rss",
        "/nasional/rss", "/news/rss",
        "/tag/telkomsel/feed", "/tag/indosat/feed",
        "/tag/xl/feed", "/tag/smartfren/feed",
        "/tag/telekomunikasi/feed",
        "/category/teknologi/feed",
        "/category/telecom/feed",
        "/category/inet/feed",
        "/category/telco/feed",
    ]

    FEED_BLACKLIST = [
        "/feed",
        "/feed/",
        "/feed/rss",
        "/feed/rss2",
        "/feed/atom",
        "/feeds/rss",
        "/index.xml",
    ]

    SUBDOMAIN_PATTERNS = {
        "detik.com":    ["inet", "finance", "news"],
        "kompas.com":   ["tekno", "money", "nasional"],
        "bisnis.com":   ["teknologi", "industri", "ekonomi"],
        "kontan.co.id": ["industri", "investasi", "nasional", "tekno"],
        "tribunnews.com": ["techno", "bisnis"],
    }

    RSS_SUBDOMAIN_PATTERNS = {
        "tempo.co": ["nasional", "bisnis", "tekno", "metro"],
    }

    KNOWN_FEEDS = {
        "detik_inet": {
            "url": "https://inet.detik.com/rss",
            "title": "detikINET",
            "source": "detik",
            "category": "teknologi",
        },
        "detik_finance": {
            "url": "https://finance.detik.com/rss",
            "title": "detikFinance",
            "source": "detik",
            "category": "bisnis",
        },
        "detik_news": {
            "url": "https://news.detik.com/rss",
            "title": "detikNews",
            "source": "detik",
            "category": "umum",
        },
        "tempo_nasional": {
            "url": "https://rss.tempo.co/nasional",
            "title": "Tempo Nasional",
            "source": "tempo",
            "category": "nasional",
        },
        "tempo_bisnis": {
            "url": "https://rss.tempo.co/bisnis",
            "title": "Tempo Bisnis",
            "source": "tempo",
            "category": "bisnis",
        },
        "cnn_ekonomi": {
            "url": "https://www.cnnindonesia.com/ekonomi/rss",
            "title": "CNN Indonesia Ekonomi",
            "source": "cnnindonesia",
            "category": "ekonomi",
        },
        "cnn_teknologi": {
            "url": "https://www.cnnindonesia.com/teknologi/rss",
            "title": "CNN Indonesia Teknologi",
            "source": "cnnindonesia",
            "category": "teknologi",
        },
        "cnbc_tech": {
            "url": "https://www.cnbcindonesia.com/tech/rss",
            "title": "CNBC Indonesia Tech",
            "source": "cnbcindonesia",
            "category": "teknologi",
        },
        "kontan_industri": {
            "url": "https://industri.kontan.co.id/rss",
            "title": "Kontan Industri",
            "source": "kontan",
            "category": "industri",
        },
        "kontan_investasi": {
            "url": "https://investasi.kontan.co.id/rss",
            "title": "Kontan Investasi",
            "source": "kontan",
            "category": "investasi",
        },
        "republika": {
            "url": "https://republika.co.id/rss",
            "title": "Republika",
            "source": "republika",
            "category": "umum",
        },
        "tribunnews": {
            "url": "https://www.tribunnews.com/rss",
            "title": "Tribunnews",
            "source": "tribunnews",
            "category": "umum",
        },
        "kompas_tekno": {
            "url": "https://tekno.kompas.com/rss/headline.xml",
            "title": "Kompas Tekno",
            "source": "kompas",
            "category": "teknologi",
        },
        "kompas_money": {
            "url": "https://money.kompas.com/rss/headline.xml",
            "title": "Kompas Money",
            "source": "kompas",
            "category": "bisnis",
        },
        "bisnis_telko": {
            "url": "https://bisnis.com/feed/rss/industri/telekomunikasi",
            "title": "Bisnis Telekomunikasi",
            "source": "bisnis",
            "category": "telekomunikasi",
        },
    }

    QUALITY_THRESHOLD = 10

    # ─────────────────────────────────────────────
    # METHOD 1 — HTML auto-discovery
    # ─────────────────────────────────────────────
    def discover_from_html(self, base_url: str) -> list:
        """Scan <link rel='alternate'> di <head> HTML."""
        found = []
        try:
            resp = requests.get(
                base_url, headers=self.HEADERS, timeout=15
            )
            soup = BeautifulSoup(resp.content, "html.parser")
            for link in soup.find_all("link", type=[
                "application/rss+xml",
                "application/atom+xml",
                "application/feed+json"
            ]):
                href = link.get("href", "")
                if href:
                    href     = href if isinstance(href, str) else "".join(href)
                    full_url = urljoin(base_url, href)
                    found.append(full_url)
                    print(f"  [auto-discovery] {full_url}")
        except Exception as e:
            print(f"  Error html discovery {base_url}: {e}")
        return found

    # ─────────────────────────────────────────────
    # METHOD 2 — Brute-force common paths
    # ─────────────────────────────────────────────
    def brute_force_paths(self, base_url: str) -> list:
        """Coba semua common RSS paths, skip generic feeds."""
        found  = []
        parsed = urlparse(base_url)
        domain = f"{parsed.scheme}://{parsed.netloc}"

        for path in self.COMMON_PATHS:
            url = domain + path
            try:
                resp         = requests.get(
                    url, headers=self.HEADERS,
                    timeout=8, allow_redirects=True
                )
                content_type = resp.headers.get("Content-Type", "")
                is_rss       = (
                    "xml" in content_type or
                    "rss" in content_type or
                    b"<rss"  in resp.content[:500] or
                    b"<feed" in resp.content[:500] or
                    b"<?xml" in resp.content[:100]
                )
                if resp.status_code == 200 and is_rss:
                    url_path = urlparse(url).path
                    if url_path in self.FEED_BLACKLIST:
                        print(f"  [skip] Generic feed: {url}")
                        continue
                    found.append(url)
                    print(f"  [brute-force] FOUND: {url}")
            except Exception as e:
                logger.debug(f"Failed {url}: {e}")
                continue
        return found

    # ─────────────────────────────────────────────
    # METHOD 3A — Subdomain discovery
    # Pattern: {sub}.{domain}/rss
    # Contoh : inet.detik.com/rss
    # ─────────────────────────────────────────────
    def discover_subdomains(self, base_domain: str) -> list:
        """Coba RSS di subdomain yang diketahui."""
        found      = []
        subdomains = self.SUBDOMAIN_PATTERNS.get(base_domain, [])

        for sub in subdomains:
            url = f"https://{sub}.{base_domain}/rss"
            try:
                resp         = requests.get(
                    url, headers=self.HEADERS,
                    timeout=8, allow_redirects=True
                )
                content_type = resp.headers.get("Content-Type", "")
                is_rss       = (
                    "xml" in content_type or
                    "rss" in content_type or
                    b"<rss"  in resp.content[:500] or
                    b"<feed" in resp.content[:500]
                )
                if resp.status_code == 200 and is_rss:
                    found.append(url)
                    print(f"  [subdomain] FOUND: {url}")
            except Exception:
                continue
        return found

    # ─────────────────────────────────────────────
    # METHOD 3B — RSS subdomain discovery
    # Pattern: rss.{domain}/{kategori}
    # Contoh : rss.tempo.co/nasional
    # ─────────────────────────────────────────────
    def discover_rss_subdomain(self, base_domain: str) -> list:
        """Handle portal yang pakai subdomain rss. khusus."""
        found      = []
        categories = self.RSS_SUBDOMAIN_PATTERNS.get(base_domain, [])

        for cat in categories:
            url = f"https://rss.{base_domain}/{cat}"
            try:
                resp         = requests.get(
                    url, headers=self.HEADERS,
                    timeout=8, allow_redirects=True
                )
                content_type = resp.headers.get("Content-Type", "")
                is_rss       = (
                    "xml" in content_type or
                    "rss" in content_type or
                    b"<rss"  in resp.content[:500] or
                    b"<feed" in resp.content[:500]
                )
                if resp.status_code == 200 and is_rss:
                    found.append(url)
                    print(f"  [rss-subdomain] FOUND: {url}")
            except Exception:
                continue
        return found

    # ─────────────────────────────────────────────
    # METHOD 4 — Google News RSS
    # ─────────────────────────────────────────────
    def google_news_rss(self, keywords: list) -> dict:
        """Generate Google News RSS URLs per keyword telco."""
        base  = "https://news.google.com/rss/search"
        feeds = {}
        for kw in keywords:
            params    = f"?q={quote(kw)}&hl=id&gl=ID&ceid=ID:id"
            feeds[kw] = base + params
        return feeds

    # ─────────────────────────────────────────────
    # VALIDATOR
    # ─────────────────────────────────────────────
    def validate_feed(self, url: str) -> dict | None:
        """
        Fetch manual dengan requests + custom headers,
        parse dengan feedparser dari content.
        """
        try:
            resp = requests.get(
                url, headers=self.HEADERS,
                timeout=15, allow_redirects=True
            )
            if resp.status_code != 200:
                print(f"  [skip] HTTP {resp.status_code}: {url[:60]}")
                return None

            feed        = feedparser.parse(resp.content)
            entry_count = len(feed.entries)
            print(f"  [validate] {entry_count} entries — {url[:70]}")

            if entry_count == 0:
                return None

            has_content = any(
                getattr(e, "summary", None) or getattr(e, "content", None)
                for e in feed.entries[:3]
            )
            has_date = any(
                getattr(e, "published", None)
                for e in feed.entries[:3]
            )

            score  = 0
            score += min(entry_count, 10) * 3
            score += 40 if has_content else 0
            score += 30 if has_date else 0

            feed_title = ""
            if hasattr(feed, "feed"):
                feed_title = getattr(feed.feed, "title", "")

            return {
                "url":           url,
                "title":         feed_title,
                "entry_count":   entry_count,
                "has_content":   has_content,
                "has_date":      has_date,
                "quality_score": score,
            }

        except Exception as e:
            print(f"  [error] {url[:60]}: {e}")
            return None

    # ─────────────────────────────────────────────
    # KNOWN FEEDS — hardcoded portal besar
    # ─────────────────────────────────────────────
    def add_known_feeds(self, all_feeds: dict) -> dict:
        """Validasi dan tambahkan known feeds ke hasil discovery."""
        print(f"\n{'='*50}")
        print("Validating known feeds...")
        print('='*50)

        existing_urls = {
            v["url"].rstrip("/").lower()
            for v in all_feeds.values()
            if isinstance(v, dict) and "url" in v
        }

        for key, info in self.KNOWN_FEEDS.items():
            normalized = info["url"].rstrip("/").lower()

            if normalized in existing_urls:
                print(f"  [skip] Sudah ada dari discovery: {info['url']}")
                continue

            time.sleep(1.0)
            result = self.validate_feed(info["url"])

            if result:
                result["source"]   = info.get("source", "")
                result["category"] = info.get("category", "")
                all_feeds[key]     = result
                existing_urls.add(normalized)
                print(f"  ✅ {key}: {result['entry_count']} entries "
                      f"score={result['quality_score']}")
            else:
                all_feeds[key] = info
                existing_urls.add(normalized)
                print(f"  ⚠️  {key}: validasi gagal, disimpan manual")

        return all_feeds

    # ─────────────────────────────────────────────
    # DEDUPLICATION
    # ─────────────────────────────────────────────
    def deduplicate_feeds(self, feeds: dict) -> dict:
        """
        Hapus duplikasi berdasarkan URL yang dinormalisasi.
        Jika duplikat, simpan yang quality_score lebih tinggi.
        """
        seen_urls:  dict = {}
        clean_feeds: dict = {}

        for key, data in feeds.items():
            if not isinstance(data, dict) or "url" not in data:
                continue

            normalized    = data["url"].rstrip("/").lower()
            current_score = data.get("quality_score", 0)

            if normalized not in seen_urls:
                seen_urls[normalized] = key
                clean_feeds[key]      = data
            else:
                existing_key   = seen_urls[normalized]
                existing_score = clean_feeds[existing_key].get(
                    "quality_score", 0
                )
                if current_score > existing_score:
                    print(f"  [dedup] Replace {existing_key} "
                          f"(score {existing_score}) "
                          f"→ {key} (score {current_score})")
                    del clean_feeds[existing_key]
                    seen_urls[normalized] = key
                    clean_feeds[key]      = data
                else:
                    print(f"  [dedup] Skip duplikat: {data['url'][:60]}")

        print(f"\n  Sebelum dedup    : {len(feeds)} feeds")
        print(f"  Setelah dedup    : {len(clean_feeds)} feeds")
        print(f"  Duplikat dihapus : {len(feeds) - len(clean_feeds)}")
        return clean_feeds

    # ─────────────────────────────────────────────
    # MASTER RUNNER
    # ─────────────────────────────────────────────
    def run_full_discovery(self, target_sites: dict) -> dict:
        """
        Jalankan semua metode discovery, validasi,
        tambah known feeds, dedup, simpan ke YAML.
        """
        all_feeds: dict = {}

        # ── Method 1, 2, 3A, 3B: per portal ──
        for name, url in target_sites.items():
            print(f"\n{'='*50}")
            print(f"Scanning: {name} — {url}")
            print('='*50)

            found  = []
            found += self.discover_from_html(url)
            found += self.brute_force_paths(url)

            domain  = urlparse(url).netloc.replace("www.", "")
            found  += self.discover_subdomains(domain)
            found  += self.discover_rss_subdomain(domain)

            found = list(set(found))
            print(f"  → {len(found)} candidate URLs ditemukan")

            for feed_url in found:
                time.sleep(1.5)
                result = self.validate_feed(feed_url)
                if result and result["quality_score"] >= self.QUALITY_THRESHOLD:
                    key            = f"{name}_{len(all_feeds)}"
                    all_feeds[key] = result
                    print(f"  ✅ VALID: score={result['quality_score']} "
                          f"entries={result['entry_count']}")

        # ── Method 4: Google News RSS ──
        print(f"\n{'='*50}")
        print("Google News RSS")
        print('='*50)

        gn_feeds = self.google_news_rss([
            "Telkomsel",
            "Indosat",
            "XL Axiata",
            "Tri Indonesia",
            "Smartfren",
            "paket data telkomsel",
            "5G Indonesia",
            "telekomunikasi Indonesia",
        ])

        for kw, url in gn_feeds.items():
            time.sleep(1.0)
            result = self.validate_feed(url)
            if result:
                result["keyword"]              = kw
                all_feeds[f"google_news_{kw}"] = result
                print(f"  ✅ {kw}: {result['entry_count']} entries "
                      f"score={result['quality_score']}")
            else:
                print(f"  ❌ {kw}: gagal atau kosong")

        # ── Known feeds: hardcoded portal besar ──
        all_feeds = self.add_known_feeds(all_feeds)

        # ── Deduplication ──
        all_feeds = self.deduplicate_feeds(all_feeds)

        # ── Simpan ke YAML ──
        output_path = Path("configs/rss_feeds.yaml")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(
                all_feeds, f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )

        # ── Summary ──
        print(f"\n{'='*50}")
        print(f"✅ Saved {len(all_feeds)} feeds → {output_path}")
        print('='*50)

        print("\n=== SUMMARY FINAL FEEDS ===")
        sorted_feeds = sorted(
            all_feeds.items(),
            key=lambda x: x[1].get("quality_score", 0)
                if isinstance(x[1], dict) else 0,
            reverse=True,
        )
        for name, info in sorted_feeds:
            if isinstance(info, dict):
                score   = info.get("quality_score", 0)
                entries = info.get("entry_count", "-")
                url     = info.get("url", "")
                source  = info.get("source", "")
                print(f"  {score:3}pts | {str(entries):>4} entries "
                      f"| {source:<15} | {name:<35} | {url}")

        return all_feeds