import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

POSITIVE_WORDS = {
    "rally", "surge", "gain", "gains", "bullish", "upgrade",
    "growth", "boom", "recovery", "outperform",
}
NEGATIVE_WORDS = {
    "crash", "plunge", "selloff", "recession", "bearish",
    "downgrade", "default", "layoffs", "war", "slump", "slowdown",
}

MOOD_ADJUSTMENT = 0.2  # max +/-20% change to stop-loss width

RSS_FEEDS = [
    ("national", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("national", "https://www.business-standard.com/rss/markets-106.rss"),
    ("international", "https://feeds.bbci.co.uk/news/world/rss.xml"),
]


class FeedUnavailable(Exception):
    """Raised when a single RSS feed can't be fetched or parsed."""


def _fetch_feed_xml(url):
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.text


_WORD_RE = re.compile(r"[a-z]+")


def _words(title):
    # Hyphens are stripped (not treated as separators) so "sell-off" reads
    # as "selloff" and still matches the single-token lexicon above.
    return set(_WORD_RE.findall(title.lower().replace("-", "")))


def score_mood(headlines):
    """Pure function, no I/O. headlines: list of {"title", "source",
    "category"}. Counts POSITIVE_WORDS/NEGATIVE_WORDS as whole-word matches
    (not substrings) across all headline titles.
    """
    if not headlines:
        return {"score": 0.0, "label": "Unavailable", "headline_count": 0}
    positive_hits = 0
    negative_hits = 0
    for h in headlines:
        words = _words(h["title"])
        positive_hits += len(words & POSITIVE_WORDS)
        negative_hits += len(words & NEGATIVE_WORDS)
    raw_score = (positive_hits - negative_hits) / max(positive_hits + negative_hits, 1)
    score = max(-1.0, min(1.0, raw_score))
    if score >= 0.3:
        label = "Bullish"
    elif score <= -0.3:
        label = "Bearish"
    else:
        label = "Neutral"
    return {"score": round(score, 3), "label": label, "headline_count": len(headlines)}


def _parse_feed_xml(xml_text, category, source):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FeedUnavailable(str(exc)) from exc
    headlines = []
    for item in root.findall(".//item"):
        title_el = item.find("title")
        if title_el is not None and title_el.text:
            headlines.append({"title": title_el.text.strip(), "source": source, "category": category})
    return headlines


def fetch_headlines(fetch_fn=None):
    """Fetch and parse every feed in RSS_FEEDS. fetch_fn(url) -> raw XML
    text, injectable for tests (mirrors downloader.py's fetch_fn pattern,
    resolved here at call time so monkeypatching _fetch_feed_xml works even
    when callers omit fetch_fn). A single feed failing (network error or
    malformed XML) is skipped; the rest are still returned.
    """
    fetch = fetch_fn if fetch_fn is not None else _fetch_feed_xml
    headlines = []
    for category, url in RSS_FEEDS:
        try:
            xml_text = fetch(url)
            headlines.extend(_parse_feed_xml(xml_text, category, url))
        except Exception as exc:
            logger.warning("failed to fetch/parse feed %s: %s", url, exc)
            continue
    return headlines


def get_or_fetch_daily_mood(conn, day, fetch_fn=None):
    """day: a date. Returns the cached market_mood row for day.isoformat()
    if present; otherwise fetches, scores, stores (INSERT OR IGNORE, same
    idempotency pattern as downloads_log), and returns the fresh result.
    Any exception during the entire fetch-score-store pipeline is swallowed
    here -- never propagates to the caller -- and returns the neutral/"Unavailable"
    result instead.
    """
    date_str = day.isoformat()
    try:
        row = conn.execute("SELECT * FROM market_mood WHERE date = ?", (date_str,)).fetchone()
        if row is not None:
            return {
                "date": row["date"],
                "score": row["score"],
                "label": row["label"],
                "headlines": json.loads(row["headlines_json"]),
            }
        headlines = fetch_headlines(fetch_fn=fetch_fn)
        mood = score_mood(headlines)
        conn.execute(
            """INSERT OR IGNORE INTO market_mood (date, score, label, headlines_json, fetched_at)
               VALUES (?, ?, ?, ?, ?)""",
            (date_str, mood["score"], mood["label"], json.dumps(headlines), datetime.utcnow().isoformat()),
        )
        conn.commit()
        return {"date": date_str, "score": mood["score"], "label": mood["label"], "headlines": headlines}
    except Exception:
        # On any exception (cache read failure, fetch failure, score failure,
        # or DB write failure), return neutral/"Unavailable" result to
        # prevent propagation to caller
        logger.warning("market mood pipeline degraded to Unavailable for %s", date_str)
        return {
            "date": date_str,
            "score": 0.0,
            "label": "Unavailable",
            "headlines": [],
        }
