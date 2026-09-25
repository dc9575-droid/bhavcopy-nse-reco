# Market Mood News Signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface market-wide news sentiment ("mood") on the Recommendations page, and use it to widen or tighten stop-loss distance on that day's picks — never targets, never which symbols get picked.

**Architecture:** A new `nse_recommender/news.py` module fetches headlines from a small fixed list of RSS feeds, scores them with a plain keyword lexicon into a `[-1, 1]` mood score, and caches one score per calendar day in a new `market_mood` table. `recommender.py` threads that score through its existing pick-building functions as an optional `mood_score` parameter (default `0.0`, so every existing caller is unaffected unless it opts in), adjusting only `stop_loss_pct` via `alignment = mood_score if side == "buy" else -mood_score` and `adjusted = stop_loss_pct * (1 + MOOD_ADJUSTMENT * alignment)`.

**Tech Stack:** Flask, SQLite, `requests` (already a dependency), stdlib `xml.etree.ElementTree` for RSS parsing (no new dependency — matches this project's existing avoidance of extra libraries after the numpy/cPanel segfault issue).

**Spec:** `docs/superpowers/specs/2026-09-25-market-mood-news-signal-design.md`

## Global Constraints

- `MOOD_ADJUSTMENT = 0.2` — stop-loss width changes by at most ±20%.
- Target percentages are NEVER adjusted by mood — only `stop_loss_pct`.
- Mood is market-wide only — no per-stock news matching in this pass.
- Mood is computed once per calendar date and cached (`market_mood` table, `INSERT OR IGNORE`) — never refetched for a date already stored.
- A single RSS feed failing must never break the others; total feed failure must never break recommendation generation (degrades to score `0.0`, label `"Unavailable"`).
- No test in this suite may depend on real network access — a `conftest.py` autouse fixture blocks the real fetch by default; tests needing specific headlines pass their own `fetch_fn` or pre-insert a `market_mood` row.

---

## File Structure

- **Create** `nse_recommender/news.py` — headline fetching, sentiment scoring, daily caching. New, single-responsibility module (mirrors `downloader.py`'s shape: a real fetch function, a pure parsing/scoring function, and a DB-caching orchestrator).
- **Create** `tests/test_news.py` — unit tests for all three `news.py` functions.
- **Modify** `nse_recommender/db.py` — add the `market_mood` table to `SCHEMA`.
- **Modify** `tests/test_db.py` — assert the new table exists.
- **Modify** `conftest.py` (currently empty) — add the autouse network-blocking fixture.
- **Modify** `nse_recommender/recommender.py` — thread `mood_score` through `_levels`, `_build_picks`, `generate_recommendations`; wire `news.get_or_fetch_daily_mood` into `generate_and_save_all`, which now returns `(results, mood)` instead of just `results`.
- **Modify** `tests/test_recommender.py` — new tests for the mood-adjusted stop-loss math and the `generate_and_save_all` wiring.
- **Modify** `app.py` — `/recommendations` route unpacks the new tuple and passes `mood` to the template.
- **Modify** `templates/recommendations.html` — add the Market Mood banner.
- **Modify** `tests/test_integration.py` — assert the banner renders.

---

### Task 1: `market_mood` table

**Files:**
- Modify: `nse_recommender/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: a `market_mood` table with columns `date TEXT PRIMARY KEY, score REAL NOT NULL, label TEXT NOT NULL, headlines_json TEXT NOT NULL, fetched_at TEXT NOT NULL` — consumed by Task 4's `get_or_fetch_daily_mood`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
def test_init_db_creates_market_mood_table():
    conn = get_connection(":memory:")
    init_db(conn)
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "market_mood" in tables


def test_market_mood_table_columns():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute(
        "INSERT INTO market_mood (date, score, label, headlines_json, fetched_at) VALUES (?,?,?,?,?)",
        ("2026-01-01", 0.5, "Bullish", "[]", "2026-01-01T00:00:00"),
    )
    row = conn.execute("SELECT * FROM market_mood WHERE date = ?", ("2026-01-01",)).fetchone()
    assert row["score"] == 0.5
    assert row["label"] == "Bullish"
    assert row["headlines_json"] == "[]"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/d1/nse-recommender-v2 && source .venv/bin/activate && python -m pytest tests/test_db.py -k market_mood -v`
Expected: FAIL — `sqlite3.OperationalError: no such table: market_mood`

- [ ] **Step 3: Add the table to the schema**

In `nse_recommender/db.py`, add to the end of the `SCHEMA` string (before the closing `"""`):

```sql

CREATE TABLE IF NOT EXISTS market_mood (
    date TEXT PRIMARY KEY,
    score REAL NOT NULL,
    label TEXT NOT NULL,
    headlines_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/d1/nse-recommender-v2 && source .venv/bin/activate && python -m pytest tests/test_db.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd /home/d1/nse-recommender-v2
git add nse_recommender/db.py tests/test_db.py
git commit -m "Add market_mood table for daily news sentiment caching"
```

---

### Task 2: `news.score_mood` — pure sentiment scoring

**Files:**
- Create: `nse_recommender/news.py`
- Test: `tests/test_news.py`

**Interfaces:**
- Produces: `score_mood(headlines: list[dict]) -> dict` where each input headline is `{"title": str, "source": str, "category": str}` and the return is `{"score": float, "label": str, "headline_count": int}`. Consumed by Task 4's `get_or_fetch_daily_mood`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_news.py`:

```python
from nse_recommender import news


def test_score_mood_with_no_headlines_is_unavailable():
    result = news.score_mood([])
    assert result == {"score": 0.0, "label": "Unavailable", "headline_count": 0}


def test_score_mood_clearly_bullish_headlines():
    headlines = [
        {"title": "Sensex, Nifty rally as global cues turn positive", "source": "ET", "category": "national"},
        {"title": "Markets surge on strong earnings", "source": "ET", "category": "national"},
        {"title": "IT stocks see broad-based gains", "source": "BS", "category": "national"},
    ]
    result = news.score_mood(headlines)
    # 3 positive hits ("rally", "surge", "gains"), 0 negative, over 3 headlines -> 1.0
    assert result["score"] == 1.0
    assert result["label"] == "Bullish"
    assert result["headline_count"] == 3


def test_score_mood_clearly_bearish_headlines():
    headlines = [
        {"title": "Markets crash amid recession fears", "source": "ET", "category": "national"},
        {"title": "Selloff deepens as bearish sentiment grows", "source": "BS", "category": "national"},
        {"title": "Global slowdown fears trigger declines", "source": "BBC", "category": "international"},
    ]
    result = news.score_mood(headlines)
    # negative hits: crash+recession=2, selloff+bearish=2, slowdown=1 -> 5 over 3
    # headlines -> raw -1.667, clamped to -1.0
    assert result["score"] == -1.0
    assert result["label"] == "Bearish"


def test_score_mood_mixed_headlines_is_neutral():
    headlines = [
        {"title": "Sensex ends flat in a quiet session", "source": "ET", "category": "national"},
        {"title": "IT stocks gain while banks slip", "source": "BS", "category": "national"},
        {"title": "Auto sector faces mixed trade amid crash in commodity prices", "source": "BBC", "category": "international"},
    ]
    result = news.score_mood(headlines)
    # 1 positive ("gain"), 1 negative ("crash") over 3 headlines -> 0.0
    assert result["score"] == 0.0
    assert result["label"] == "Neutral"


def test_score_mood_matches_hyphenated_negative_words():
    # "Sell-off" must match the same as "selloff" -- hyphens are stripped
    # before word-matching so headline styling doesn't cause a miss.
    headlines = [{"title": "Global sell-off wipes out gains", "source": "BBC", "category": "international"}]
    result = news.score_mood(headlines)
    # "selloff" (negative) + "gains" (positive) -> net 0 over 1 headline
    assert result["score"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/d1/nse-recommender-v2 && source .venv/bin/activate && python -m pytest tests/test_news.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nse_recommender.news'`

- [ ] **Step 3: Write `nse_recommender/news.py` (score_mood only for now)**

```python
import re

POSITIVE_WORDS = {
    "rally", "surge", "gain", "gains", "bullish", "upgrade",
    "growth", "boom", "recovery", "outperform",
}
NEGATIVE_WORDS = {
    "crash", "plunge", "selloff", "recession", "bearish",
    "downgrade", "default", "layoffs", "war", "slump", "slowdown",
}

MOOD_ADJUSTMENT = 0.2  # max +/-20% change to stop-loss width

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/d1/nse-recommender-v2 && source .venv/bin/activate && python -m pytest tests/test_news.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd /home/d1/nse-recommender-v2
git add nse_recommender/news.py tests/test_news.py
git commit -m "Add news.score_mood: plain keyword-based sentiment scoring"
```

---

### Task 3: `news.fetch_headlines` — RSS collection with per-feed failure isolation

**Files:**
- Modify: `nse_recommender/news.py`
- Test: `tests/test_news.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `fetch_headlines(fetch_fn=None) -> list[dict]` (each `{"title", "source", "category"}`), and the module-level `_fetch_feed_xml(url) -> str` real fetcher, `FeedUnavailable` exception, `RSS_FEEDS` list. Consumed by Task 4's `get_or_fetch_daily_mood` and Task 5's conftest fixture (which monkeypatches `_fetch_feed_xml`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_news.py`:

```python
SAMPLE_FEED_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Sample Feed</title>
<item><title>Sensex rallies 500 points on strong FII inflows</title></item>
<item><title>Rupee steady against dollar in early trade</title></item>
</channel></rss>"""

MALFORMED_XML = "<rss><channel><item><title>Unclosed"


def test_fetch_headlines_parses_titles_from_injected_fetch_fn():
    def fake_fetch(url):
        return SAMPLE_FEED_XML

    headlines = news.fetch_headlines(fetch_fn=fake_fetch)
    titles = [h["title"] for h in headlines]
    assert "Sensex rallies 500 points on strong FII inflows" in titles
    assert "Rupee steady against dollar in early trade" in titles
    # One entry per feed in RSS_FEEDS, since every feed returns the same
    # sample XML from this fake -- confirms all configured feeds are hit.
    assert len(headlines) == 2 * len(news.RSS_FEEDS)
    assert all(h["category"] in ("national", "international") for h in headlines)


def test_fetch_headlines_skips_a_feed_that_raises_and_keeps_the_rest():
    calls = {"n": 0}

    def flaky_fetch(url):
        calls["n"] += 1
        if calls["n"] == 1:
            raise news.FeedUnavailable("simulated network error")
        return SAMPLE_FEED_XML

    headlines = news.fetch_headlines(fetch_fn=flaky_fetch)
    # First feed failed, the rest succeeded -- some headlines still returned.
    assert len(headlines) == 2 * (len(news.RSS_FEEDS) - 1)


def test_fetch_headlines_skips_malformed_xml_without_raising():
    def fake_fetch(url):
        return MALFORMED_XML

    headlines = news.fetch_headlines(fetch_fn=fake_fetch)
    assert headlines == []


def test_fetch_headlines_with_no_fetch_fn_uses_real_fetcher_and_still_degrades_safely(monkeypatch):
    # Simulates "no network available" by making the real fetcher fail --
    # fetch_headlines must swallow it, not raise.
    def always_fail(url):
        raise news.FeedUnavailable("no network in this test")

    monkeypatch.setattr(news, "_fetch_feed_xml", always_fail)
    assert news.fetch_headlines() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/d1/nse-recommender-v2 && source .venv/bin/activate && python -m pytest tests/test_news.py -v`
Expected: FAIL — `AttributeError: module 'nse_recommender.news' has no attribute 'fetch_headlines'`

- [ ] **Step 3: Add fetching/parsing to `nse_recommender/news.py`**

Add near the top (after the existing imports) and after `MOOD_ADJUSTMENT`:

```python
import xml.etree.ElementTree as ET

import requests

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
```

Add at the end of the file:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/d1/nse-recommender-v2 && source .venv/bin/activate && python -m pytest tests/test_news.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd /home/d1/nse-recommender-v2
git add nse_recommender/news.py tests/test_news.py
git commit -m "Add news.fetch_headlines: RSS collection with per-feed failure isolation"
```

---

### Task 4: `news.get_or_fetch_daily_mood` — daily caching

**Files:**
- Modify: `nse_recommender/news.py`
- Test: `tests/test_news.py`

**Interfaces:**
- Consumes: `fetch_headlines(fetch_fn=None)` and `score_mood(headlines)` from Tasks 2-3; the `market_mood` table from Task 1.
- Produces: `get_or_fetch_daily_mood(conn, day, fetch_fn=None) -> dict` with keys `{"date": str, "score": float, "label": str, "headlines": list[dict]}`. Consumed by Task 7's `generate_and_save_all`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_news.py`:

```python
import json
from datetime import date

from nse_recommender.db import get_connection, init_db


def test_get_or_fetch_daily_mood_computes_and_stores_a_new_day():
    conn = get_connection(":memory:")
    init_db(conn)

    def fake_fetch(url):
        return SAMPLE_FEED_XML

    mood = news.get_or_fetch_daily_mood(conn, date(2026, 9, 25), fetch_fn=fake_fetch)
    assert mood["date"] == "2026-09-25"
    assert mood["label"] in ("Bullish", "Neutral", "Bearish")
    assert len(mood["headlines"]) == 2 * len(news.RSS_FEEDS)

    row = conn.execute("SELECT * FROM market_mood WHERE date = ?", ("2026-09-25",)).fetchone()
    assert row is not None
    assert json.loads(row["headlines_json"]) == mood["headlines"]


def test_get_or_fetch_daily_mood_returns_cached_result_without_refetching():
    conn = get_connection(":memory:")
    init_db(conn)
    calls = {"n": 0}

    def counting_fetch(url):
        calls["n"] += 1
        return SAMPLE_FEED_XML

    first = news.get_or_fetch_daily_mood(conn, date(2026, 9, 25), fetch_fn=counting_fetch)
    calls_after_first = calls["n"]
    second = news.get_or_fetch_daily_mood(conn, date(2026, 9, 25), fetch_fn=counting_fetch)

    assert second == first
    assert calls["n"] == calls_after_first  # no new fetch calls on the second lookup


def test_get_or_fetch_daily_mood_degrades_to_neutral_when_all_feeds_fail():
    conn = get_connection(":memory:")
    init_db(conn)

    def always_fail(url):
        raise news.FeedUnavailable("simulated outage")

    mood = news.get_or_fetch_daily_mood(conn, date(2026, 9, 25), fetch_fn=always_fail)
    assert mood["score"] == 0.0
    assert mood["label"] == "Unavailable"
    assert mood["headlines"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/d1/nse-recommender-v2 && source .venv/bin/activate && python -m pytest tests/test_news.py -v`
Expected: FAIL — `AttributeError: module 'nse_recommender.news' has no attribute 'get_or_fetch_daily_mood'`

- [ ] **Step 3: Add caching to `nse_recommender/news.py`**

Add `import json` and `from datetime import datetime` to the top of the file (alongside the existing imports), then add at the end of the file:

```python
def get_or_fetch_daily_mood(conn, day, fetch_fn=None):
    """day: a date. Returns the cached market_mood row for day.isoformat()
    if present; otherwise fetches, scores, stores (INSERT OR IGNORE, same
    idempotency pattern as downloads_log), and returns the fresh result.
    Any exception while fetching is swallowed here -- never propagates to
    the caller -- and treated as the empty-headlines case.
    """
    date_str = day.isoformat()
    row = conn.execute("SELECT * FROM market_mood WHERE date = ?", (date_str,)).fetchone()
    if row is not None:
        return {
            "date": row["date"],
            "score": row["score"],
            "label": row["label"],
            "headlines": json.loads(row["headlines_json"]),
        }
    try:
        headlines = fetch_headlines(fetch_fn=fetch_fn)
    except Exception:
        headlines = []
    mood = score_mood(headlines)
    conn.execute(
        """INSERT OR IGNORE INTO market_mood (date, score, label, headlines_json, fetched_at)
           VALUES (?, ?, ?, ?, ?)""",
        (date_str, mood["score"], mood["label"], json.dumps(headlines), datetime.utcnow().isoformat()),
    )
    conn.commit()
    return {"date": date_str, "score": mood["score"], "label": mood["label"], "headlines": headlines}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/d1/nse-recommender-v2 && source .venv/bin/activate && python -m pytest tests/test_news.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd /home/d1/nse-recommender-v2
git add nse_recommender/news.py tests/test_news.py
git commit -m "Add news.get_or_fetch_daily_mood: per-day caching with safe degradation"
```

---

### Task 5: Block real network access in the test suite by default

**Files:**
- Modify: `conftest.py` (repo root, currently empty)

**Interfaces:**
- Consumes: `news.FeedUnavailable` and `news._fetch_feed_xml` from Task 3.
- Produces: an autouse fixture so no test in this suite can accidentally make a real HTTP call to an RSS feed. Tests that need specific headlines must pass their own `fetch_fn` (as Task 4's tests already do) or pre-insert a `market_mood` row (as Task 7's tests will do) — both bypass this fixture, since it only stubs the fallback path.

- [ ] **Step 1: Write the fixture**

Replace the entire contents of `conftest.py` with:

```python
import pytest

from nse_recommender import news


@pytest.fixture(autouse=True)
def _block_real_news_fetch(monkeypatch):
    """No test in this suite should depend on real network access. Any code
    path that falls through to news._fetch_feed_xml (i.e. doesn't pass its
    own fetch_fn) gets a simulated outage instead of a real HTTP call.
    """
    def _raise(url):
        raise news.FeedUnavailable("real network access disabled in tests")

    monkeypatch.setattr(news, "_fetch_feed_xml", _raise)
```

- [ ] **Step 2: Run the full suite to confirm nothing broke and nothing got slower**

Run: `cd /home/d1/nse-recommender-v2 && source .venv/bin/activate && python -m pytest -q`
Expected: all tests PASS, and the run stays fast (well under a second of added time) — proving no test fell through to a real network call.

- [ ] **Step 3: Commit**

```bash
cd /home/d1/nse-recommender-v2
git add conftest.py
git commit -m "Block real network access in tests by default (news feeds)"
```

---

### Task 6: Thread `mood_score` through the pick-building functions

**Files:**
- Modify: `nse_recommender/recommender.py`
- Test: `tests/test_recommender.py`

**Interfaces:**
- Consumes: `news.MOOD_ADJUSTMENT` from Task 2.
- Produces: `_levels(entry, side, target_pct, stop_loss_pct, mood_score=0.0)`, `_build_picks(conn, rows, side, config, mood_score=0.0)`, `generate_recommendations(conn, symbols, horizon_key, mood_score=0.0)` — all backward compatible (default `0.0` reproduces today's exact numbers). Consumed by Task 7's `generate_and_save_all`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_recommender.py`:

```python
def test_levels_buy_with_zero_mood_matches_unadjusted_baseline():
    target, stop_loss = recommender._levels(100, "buy", 0.05, 0.025, mood_score=0.0)
    assert target == 105.0
    assert stop_loss == 97.5


def test_levels_buy_with_aligned_bullish_mood_widens_stop_loss():
    target, stop_loss = recommender._levels(100, "buy", 0.05, 0.025, mood_score=1.0)
    assert target == 105.0  # target never changes
    assert stop_loss == 97.0  # 0.025 * (1 + 0.2*1.0) = 0.03 -> 100*(1-0.03)


def test_levels_sell_with_bullish_mood_tightens_stop_loss():
    # Bullish mood disagrees with a sell pick (alignment = -mood_score = -1.0).
    target, stop_loss = recommender._levels(100, "sell", 0.05, 0.025, mood_score=1.0)
    assert target == 95.0  # target never changes
    assert stop_loss == 102.0  # 0.025 * (1 + 0.2*-1.0) = 0.02 -> 100*(1+0.02)


def test_generate_recommendations_threads_mood_score_into_buy_stop_loss(seeded_conn):
    baseline = recommender.generate_recommendations(seeded_conn, SYMBOLS, "short_term", mood_score=0.0)
    bullish = recommender.generate_recommendations(seeded_conn, SYMBOLS, "short_term", mood_score=1.0)
    entry = bullish["buy"][0]["entry"]
    assert baseline["buy"][0]["stop_loss"] == round(entry * 0.975, 2)
    assert bullish["buy"][0]["stop_loss"] == round(entry * 0.97, 2)
    # Targets never move regardless of mood.
    assert baseline["buy"][0]["target"] == bullish["buy"][0]["target"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/d1/nse-recommender-v2 && source .venv/bin/activate && python -m pytest tests/test_recommender.py -k "levels or threads_mood" -v`
Expected: FAIL — `TypeError: _levels() got an unexpected keyword argument 'mood_score'`

- [ ] **Step 3: Update `nse_recommender/recommender.py`**

Add to the imports at the top:

```python
from nse_recommender import chart, channel, news, streaks
```

(replacing the existing `from nse_recommender import chart, channel, streaks` line — `news` is now also needed for `MOOD_ADJUSTMENT`.)

Replace `_levels`:

```python
def _levels(entry, side, target_pct, stop_loss_pct, mood_score=0.0):
    alignment = mood_score if side == "buy" else -mood_score
    adjusted_stop_loss_pct = stop_loss_pct * (1 + news.MOOD_ADJUSTMENT * alignment)
    if side == "buy":
        return entry * (1 + target_pct), entry * (1 - adjusted_stop_loss_pct)
    return entry * (1 - target_pct), entry * (1 + adjusted_stop_loss_pct)
```

Replace `_build_picks`:

```python
def _build_picks(conn, rows, side, config, mood_score=0.0):
    picks = []
    for _, row in rows.iterrows():
        target, stop_loss = _levels(
            row["entry"], side, config["target_pct"], config["stop_loss_pct"], mood_score
        )
        pct = row["pct_return"] * 100
        picks.append({
            "symbol": row["symbol"],
            "entry": round(row["entry"], 2),
            "entry_date": row["entry_date"],
            "target": round(target, 2),
            "stop_loss": round(stop_loss, 2),
            "reason": f"{pct:+.1f}% over last {config['lookback_days']} trading days",
            "streak": streaks.current_streak(conn, row["symbol"]),
            "channel": channel.compute_channel(conn, row["symbol"]),
        })
    for pick in picks:
        pick["chart_svg"] = chart.channel_svg(pick["channel"])
        pick["next_chart_svg"] = chart.next_day_projection_svg(pick["channel"])
    return picks
```

Replace `generate_recommendations`:

```python
def generate_recommendations(conn, symbols, horizon_key, mood_score=0.0):
    config = HORIZONS[horizon_key]
    try:
        ranked = compute_returns(conn, symbols, config["lookback_days"])
    except InsufficientData as exc:
        return {"status": "insufficient_data", "have": exc.have, "need": exc.need, "label": config["label"]}
    top5 = ranked.head(5)
    bottom5 = ranked.tail(5).iloc[::-1]
    return {
        "status": "ok",
        "label": config["label"],
        "buy": _build_picks(conn, top5, "buy", config, mood_score),
        "sell": _build_picks(conn, bottom5, "sell", config, mood_score),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/d1/nse-recommender-v2 && source .venv/bin/activate && python -m pytest tests/test_recommender.py -v`
Expected: all PASS (including every pre-existing test — `mood_score` defaults to `0.0`, reproducing identical numbers)

- [ ] **Step 5: Run the full suite**

Run: `cd /home/d1/nse-recommender-v2 && source .venv/bin/activate && python -m pytest -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
cd /home/d1/nse-recommender-v2
git add nse_recommender/recommender.py tests/test_recommender.py
git commit -m "Thread mood_score through pick-building (stop-loss only, target untouched)"
```

---

### Task 7: Wire `generate_and_save_all` to the daily mood

**Files:**
- Modify: `nse_recommender/recommender.py`
- Modify: `app.py`
- Test: `tests/test_recommender.py`

**Interfaces:**
- Consumes: `news.get_or_fetch_daily_mood(conn, day, fetch_fn=None)` from Task 4; `generate_recommendations(conn, symbols, horizon_key, mood_score=0.0)` from Task 6.
- Produces: `generate_and_save_all(conn, symbols, generated_date) -> (results, mood)` — a **breaking return-type change** (was `results` alone). Consumed by Task 8's template rendering. (Existing tests that call this function without capturing its return value are unaffected.)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_recommender.py` (this file already imports `from datetime import date, timedelta` at the top):

```python
def test_generate_and_save_all_returns_mood_alongside_results(seeded_conn):
    results, mood = recommender.generate_and_save_all(seeded_conn, SYMBOLS, generated_date="2024-01-11")
    assert results["short_term"]["status"] == "ok"
    # No market_mood row was pre-inserted and the test suite blocks real
    # network by default (see conftest.py), so this must degrade to neutral.
    assert mood["score"] == 0.0
    assert mood["label"] == "Unavailable"


def test_generate_and_save_all_applies_a_cached_mood_score_to_stop_loss(seeded_conn):
    seeded_conn.execute(
        "INSERT INTO market_mood (date, score, label, headlines_json, fetched_at) VALUES (?, ?, ?, ?, ?)",
        ("2024-01-11", 1.0, "Bullish", "[]", "2024-01-11T00:00:00"),
    )
    seeded_conn.commit()

    results, mood = recommender.generate_and_save_all(seeded_conn, SYMBOLS, generated_date="2024-01-11")

    assert mood["score"] == 1.0
    assert mood["label"] == "Bullish"
    top_buy = results["short_term"]["buy"][0]
    assert top_buy["stop_loss"] == round(top_buy["entry"] * 0.97, 2)  # widened, mood-aligned buy
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/d1/nse-recommender-v2 && source .venv/bin/activate && python -m pytest tests/test_recommender.py -k "returns_mood or applies_a_cached" -v`
Expected: FAIL — `ValueError: too many values to unpack` (function still returns a single dict, not a tuple)

- [ ] **Step 3: Update `generate_and_save_all` in `nse_recommender/recommender.py`**

Add `from datetime import date` to the top of `nse_recommender/recommender.py` (it currently has no `datetime` import — this is a new addition to that file specifically; `app.py` importing `date` separately is unrelated).

Replace `generate_and_save_all`:

```python
def generate_and_save_all(conn, symbols, generated_date):
    day = date.fromisoformat(generated_date)
    mood = news.get_or_fetch_daily_mood(conn, day)
    results = {}
    for horizon_key in HORIZONS:
        result = generate_recommendations(conn, symbols, horizon_key, mood_score=mood["score"])
        save_recommendations(conn, horizon_key, generated_date, result)
        results[horizon_key] = result
    return results, mood
```

- [ ] **Step 4: Update the one in-repo caller (`app.py`)**

In `app.py`, the `/recommendations` route currently reads:

```python
            results = recommender.generate_and_save_all(
                conn, current_app.config["SYMBOLS"], generated_date
            )
        finally:
            conn.close()
        return render_template("recommendations.html", results=results, generated_date=generated_date)
```

Change it to:

```python
            results, mood = recommender.generate_and_save_all(
                conn, current_app.config["SYMBOLS"], generated_date
            )
        finally:
            conn.close()
        return render_template(
            "recommendations.html", results=results, generated_date=generated_date, mood=mood
        )
```

(`templates/recommendations.html` doesn't reference `mood` yet — that's Task 8 — so this just makes the variable available; the page renders identically until then.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/d1/nse-recommender-v2 && source .venv/bin/activate && python -m pytest tests/test_recommender.py tests/test_integration.py -v`
Expected: all PASS

- [ ] **Step 6: Run the full suite**

Run: `cd /home/d1/nse-recommender-v2 && source .venv/bin/activate && python -m pytest -q`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
cd /home/d1/nse-recommender-v2
git add nse_recommender/recommender.py app.py tests/test_recommender.py
git commit -m "Wire generate_and_save_all to the daily market mood"
```

---

### Task 8: Market Mood banner on the Recommendations page

**Files:**
- Modify: `templates/recommendations.html`
- Test: `tests/test_integration.py`

**Interfaces:**
- Consumes: the `mood` template variable (`{"date", "score", "label", "headlines"}`) already passed by `app.py` since Task 7.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_integration.py`:

```python
def test_recommendations_page_shows_market_mood_banner(client):
    resp = client.get("/recommendations")
    body = resp.data.decode()
    assert "Market Mood" in body
    # No feeds are reachable in tests (conftest.py blocks real network and
    # no market_mood row was pre-seeded), so this must show the neutral
    # degraded state, not crash or silently omit the banner.
    assert "Unavailable" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/d1/nse-recommender-v2 && source .venv/bin/activate && python -m pytest tests/test_integration.py -k market_mood -v`
Expected: FAIL — `assert "Market Mood" in body` fails (banner doesn't exist yet)

- [ ] **Step 3: Add the banner to `templates/recommendations.html`**

Insert immediately after the `<h1>Recommendations ...</h1>` line and before the `{% for horizon_key, result in results.items() %}` loop:

```html
<div class="card">
  <p><strong>Market Mood: {{ mood.label }}</strong> <span class="muted">(score {{ mood.score }})</span></p>
  {% if mood.headlines %}
  <ul class="muted">
    {% for h in mood.headlines[:5] %}<li>{{ h.title }} <span class="muted">({{ h.source }})</span></li>{% endfor %}
  </ul>
  {% endif %}
</div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/d1/nse-recommender-v2 && source .venv/bin/activate && python -m pytest tests/test_integration.py -v`
Expected: all PASS

- [ ] **Step 5: Run the full suite**

Run: `cd /home/d1/nse-recommender-v2 && source .venv/bin/activate && python -m pytest -q`
Expected: all PASS (this project had 95 tests before this plan; expect that count to have grown by the tests added in Tasks 1-8)

- [ ] **Step 6: Commit**

```bash
cd /home/d1/nse-recommender-v2
git add templates/recommendations.html tests/test_integration.py
git commit -m "Add Market Mood banner to the Recommendations page"
```

---

### Task 9: Browser verification and push

**Files:** none (verification only)

- [ ] **Step 1: Start the preview server** (via the `nse-recommender` launch config) and open `/recommendations`.

- [ ] **Step 2: Confirm the Market Mood banner renders** with a label and score (likely "Unavailable"/0.0 in this environment, since outbound RSS access may not be reachable from the dev sandbox — that degraded state rendering correctly, without an error page, is itself the thing to verify).

- [ ] **Step 3: Check the browser console/network tab for errors** on that page load.

- [ ] **Step 4: Resize to mobile width (375px)** and confirm the banner doesn't break the existing responsive layout (it reuses `.card`/`.muted`, so this should be a quick confirmation, not new work).

- [ ] **Step 5: Reset the viewport to desktop.**

- [ ] **Step 6: Push**

```bash
cd /home/d1/nse-recommender-v2
git push
```

---

## Self-Review Notes

- **Spec coverage:** every component in the spec (news.py's three functions, the `market_mood` table, the `_levels`/`_build_picks`/`generate_recommendations`/`generate_and_save_all` threading, the `/recommendations` wiring, the template banner, error handling, and the testing approach) has a corresponding task above. The spec listed the sentiment lexicon as illustrative (`e.g.`); Task 2 narrows it to single-word tokens only (dropping the spec's two-word phrases like "record high"/"inflation surge") specifically because multi-word negative phrases can contain a positive word as a substring (e.g. "inflation surge" contains "surge") — a real double-counting bug caught during planning. This is a lexicon-content refinement, not an architecture change.
- **Placeholder scan:** no TBD/TODO; every step has real code and real run commands.
- **Type consistency:** `_levels` → `_build_picks` → `generate_recommendations` → `generate_and_save_all` all pass `mood_score` (a plain float) with the same name and default (`0.0`) throughout. `get_or_fetch_daily_mood`'s returned dict shape (`date`, `score`, `label`, `headlines`) is used identically in Task 7's assertions and Task 8's template.
- **New test-suite-wide constraint:** Task 5's `conftest.py` fixture is the one piece of this plan that isn't scoped to a single file — it protects every future test in the suite from accidental network calls, not just the ones added here.
