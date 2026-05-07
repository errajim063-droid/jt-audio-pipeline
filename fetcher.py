"""RSS fetcher — pulls and keyword-filters articles for each of the 4 segments."""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import feedparser
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── Source lists ────────────────────────────────────────────────────────────────

SOURCES_MAROC_GENERAL = [
    "https://medias24.com/feed",
    "https://telquel.ma/feed",
    "https://leseco.ma/feed",
    "https://www.h24info.ma/feed",
    "https://aujourd8.ma/feed",
    "https://www.challenge.ma/feed",
    "https://www.lematin.ma/rss.xml",
    "https://fr.le360.ma/rss.xml",
    "https://www.lavieeco.com/feed",
    "https://www.finances.gov.ma/fr/rss",
]

SOURCES_MAP = [
    "https://www.map.ma/fr/rss",
    "https://www.mapbusiness.ma/fr/rss",
    "https://www.mapecologie.ma/fr/rss",
]

SOURCES_CASA = [
    "https://medias24.com/feed",
    "https://www.casainvest.ma/actualites/rss",
    "https://casa-amenagement.ma/rss",
    "https://www.h24info.ma/feed",
    "https://aujourdhui.ma/feed",
]

SOURCES_TECH_INTL = [
    "https://techcrunch.com/feed",
    "https://www.theverge.com/rss/index.xml",
    "https://usine-digitale.fr/rss/all.xml",
    "https://www.wired.com/feed/rss",
    "https://feeds.feedburner.com/venturebeat/SZYF",
    "https://www.technologyreview.com/feed",
    "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
    "https://feeds.reuters.com/reuters/technologyNews",
    "https://www.lemonde.fr/pixels/rss_full.xml",
    "https://www.journaldunet.com/rss",
]

# ── Keyword sets ────────────────────────────────────────────────────────────────

TECH_AI_KW = [
    "ia", "intelligence artificielle", "ai", "llm", "machine learning",
    "deep learning", "chatgpt", "chatbot", "openai", "deepmind", "mistral",
    "tech", "numérique", "digital", "startup", "algorithme", "données",
    "robotique", "automatisation", "technologie", "innovation", "big data",
    "cloud", "cybersécurité", "blockchain", "métavers", "réalité augmentée",
    "gpt", "modèle de langage", "generative", "génératif",
]

CASA_KW = [
    "casablanca", "casa", "settat", "grand casablanca", "casa-settat",
    "région casa", "wilaya", "anfa", "maârif", "hay hassani", "ain sebaa",
    "sidi bernoussi", "nouaceur", "mohammedia", "bouskoura",
]

# ── HTTP helpers ────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; JT-Radio-Pipeline/1.0; "
        "contact: errajim063@gmail.com)"
    )
}
FETCH_TIMEOUT = 15
MAX_AGE_HOURS = 24


def _strip_html(raw: str) -> str:
    """Remove HTML tags and condense whitespace."""
    clean = BeautifulSoup(raw or "", "html.parser").get_text(separator=" ")
    return re.sub(r"\s+", " ", clean).strip()


def _entry_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def fetch_feed(url: str) -> List[Dict]:
    """Fetch one RSS feed, return list of article dicts (last 24 h)."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
    articles = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=FETCH_TIMEOUT)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        feed_title = feed.feed.get("title", url)

        for entry in feed.entries:
            pub = _entry_date(entry)
            if pub and pub < cutoff:
                continue

            title = _strip_html(entry.get("title", "")).strip()
            if not title:
                continue

            summary_raw = entry.get("summary", entry.get("description", ""))
            summary = _strip_html(summary_raw)[:600]

            articles.append({
                "title": title,
                "summary": summary,
                "url": entry.get("link", ""),
                "source": feed_title,
                "published": pub.isoformat() if pub else None,
            })

    except requests.HTTPError as exc:
        logger.warning("HTTP %s fetching %s — skipped", exc.response.status_code, url)
    except Exception as exc:
        logger.warning("Error fetching %s: %s — skipped", url, exc)

    return articles


# ── Keyword filter ──────────────────────────────────────────────────────────────

def _matches(article: Dict, keywords: List[str]) -> bool:
    haystack = (article["title"] + " " + article["summary"]).lower()
    return any(kw in haystack for kw in keywords)


# ── Segment builders ────────────────────────────────────────────────────────────

def _collect(sources: List[str]) -> List[Dict]:
    """Fetch all sources, merge, deduplicate by URL."""
    seen: set[str] = set()
    result = []
    for url in sources:
        for art in fetch_feed(url):
            if art["url"] and art["url"] not in seen:
                seen.add(art["url"])
                result.append(art)
    return result


def fetch_all_segments() -> Dict[str, List[Dict]]:
    """Return dict with up-to 4 articles per segment (3 for Casablanca)."""

    logger.info("Fetching Maroc general feeds...")
    maroc_pool = _collect(SOURCES_MAROC_GENERAL)

    logger.info("Fetching MAP feeds...")
    map_pool = _collect(SOURCES_MAP)

    logger.info("Fetching Casablanca feeds...")
    casa_pool_raw = _collect(SOURCES_CASA)

    logger.info("Fetching Tech international feeds...")
    intl_pool = _collect(SOURCES_TECH_INTL)

    # Segment 1 — IA & Tech Maroc
    seg1 = [a for a in maroc_pool if _matches(a, TECH_AI_KW)][:4]

    # Segment 2 — IA & Tech International
    seg2 = [a for a in intl_pool if _matches(a, TECH_AI_KW)][:4]

    # Segment 3 — Casablanca (all themes, keyword-filtered by location)
    seg3 = [a for a in casa_pool_raw if _matches(a, CASA_KW)][:3]

    # Segment 4 — Grandes lignes nationales (MAP first, then Maroc général, no tech)
    all_national = map_pool + [a for a in maroc_pool if not _matches(a, TECH_AI_KW)]
    seen_nat: set[str] = set()
    seg4 = []
    for art in all_national:
        if art["url"] not in seen_nat:
            seen_nat.add(art["url"])
            seg4.append(art)
        if len(seg4) == 4:
            break

    segments = {
        "ia_tech_maroc": seg1,
        "ia_tech_international": seg2,
        "casablanca": seg3,
        "nationales": seg4,
    }

    for name, arts in segments.items():
        count = len(arts)
        if count == 0:
            logger.warning("Segment '%s': 0 articles", name)
        else:
            logger.info("Segment '%s': %d articles", name, count)

    return segments
