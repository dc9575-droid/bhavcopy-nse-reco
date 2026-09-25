import re
import xml.etree.ElementTree as ET

import requests

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
    ("international", "http://feeds.bbci.co.uk/news/world/rss.xml"),
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
    raw_score = (positive_hits - negative_hits) / len(headlines)
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
        except Exception:
            continue
    return headlines
