# Market Mood News Signal — Design

## Goal

Surface international/national market-moving news alongside recommendations,
and use it as a market-wide "mood" signal that adjusts the risk parameters
(stop-loss width) of that day's picks — without pretending to predict
anything, and without changing which symbols get recommended.

## Why not per-stock, why not ranking

Two constraints came out of design discussion and shape everything below:

- The ranking is relative (top-5/bottom-5 by trailing return). A market-wide
  score is the same for every stock, so adding it to every stock's return
  changes nothing about the ranking — the same 5 stocks still come out on
  top. A market-wide signal can only affect something *other than* selection.
- Matching arbitrary headlines to specific Nifty 500 symbols reliably is a
  hard, fuzzy problem on its own. Scope is market-wide only for this pass.

So the signal's only effect is on stop-loss width — a risk-tolerance knob,
not a claim about future price.

## Components

### `nse_recommender/news.py` (new module)

```python
RSS_FEEDS = [
    ("national", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("national", "https://www.business-standard.com/rss/markets-106.rss"),
    ("international", "http://feeds.bbci.co.uk/news/world/rss.xml"),
]

POSITIVE_WORDS = {"rally", "surge", "gain", "gains", "bullish", "upgrade",
                   "record high", "growth", "boom", "recovery", "outperform"}
NEGATIVE_WORDS = {"crash", "plunge", "sell-off", "selloff", "recession",
                   "bearish", "downgrade", "default", "layoffs", "war",
                   "inflation surge", "slump", "slowdown"}

MOOD_ADJUSTMENT = 0.2  # max +/-20% change to stop-loss width


class FeedUnavailable(Exception):
    """Raised when a feed can't be fetched/parsed; caller degrades to neutral."""


def fetch_headlines(fetch_fn=None):
    """Fetch and parse all RSS_FEEDS. fetch_fn(url) -> raw XML text, injectable
    for tests (mirrors downloader.py's fetch_fn pattern). Returns a list of
    {"title": str, "source": str, "category": "national"|"international"}.
    A single feed failing is swallowed (skip that feed, keep the rest) --
    total failure across all feeds yields an empty list, not an exception.
    """

def score_mood(headlines):
    """Pure function, no I/O. Counts POSITIVE_WORDS/NEGATIVE_WORDS occurrences
    (case-insensitive substring match) across all headline titles.
    score = (positive_hits - negative_hits) / max(len(headlines), 1),
    clamped to [-1.0, 1.0].
    Returns {"score": float, "label": "Bullish"|"Neutral"|"Bearish",
             "headline_count": int}.
    Empty headlines list -> score 0.0, label "Unavailable".
    Label thresholds: score >= 0.3 -> "Bullish", score <= -0.3 -> "Bearish",
    else "Neutral".
    """

def get_or_fetch_daily_mood(conn, day, fetch_fn=None):
    """day: date. Checks market_mood table for day.isoformat(); if present,
    returns the stored row as a dict. Otherwise calls fetch_headlines +
    score_mood, stores the result (INSERT OR IGNORE, same idempotency
    pattern as downloads_log), and returns it. Any exception during fetch
    is caught here and treated as the empty-headlines case (neutral,
    "Unavailable") -- never propagates to the caller.
    Returned dict: {"date", "score", "label", "headlines": [...]}
    (headlines_json column deserialized back to a list for callers).
    """
```

### Schema addition (`nse_recommender/db.py`)

```sql
CREATE TABLE IF NOT EXISTS market_mood (
    date TEXT PRIMARY KEY,
    score REAL NOT NULL,
    label TEXT NOT NULL,
    headlines_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
```

`headlines_json` stores `json.dumps(headlines)` (each `{"title", "source",
"category"}`) — so the mood is auditable from the stored row alone, not
recomputed from possibly-changed live feeds later.

### Recommender integration (`nse_recommender/recommender.py`)

- `_levels(entry, side, target_pct, stop_loss_pct, mood_score=0.0)`:
  target math is unchanged. Stop-loss becomes:
  ```python
  alignment = mood_score if side == "buy" else -mood_score
  adjusted_stop_loss_pct = stop_loss_pct * (1 + MOOD_ADJUSTMENT * alignment)
  ```
  (`MOOD_ADJUSTMENT` imported from `news.py`.) `mood_score=0.0` default
  means every existing caller/test that doesn't pass it keeps today's exact
  behavior — no adjustment.
- `_build_picks(conn, rows, side, config, mood_score=0.0)` threads
  `mood_score` down into `_levels`.
- `generate_recommendations(conn, symbols, horizon_key, mood_score=0.0)`
  threads it into `_build_picks` for both buy and sell.
- `generate_and_save_all(conn, symbols, generated_date)`: fetches
  `news.get_or_fetch_daily_mood(conn, generated_date)` once, passes its
  `score` into `generate_recommendations` for every horizon, and returns
  the mood dict alongside the existing per-horizon results (e.g. under a
  `"_mood"` key or as a second return value — implementation plan decides
  the exact shape) so the route can render it without a second lookup.

### Route (`app.py`)

`/recommendations` already calls `generate_and_save_all`; it additionally
passes the mood dict to `render_template` so the page can show the banner.
No new route needed.

### Template (`templates/recommendations.html`)

A banner near the top, above the per-horizon sections:

```html
<div class="card">
  <p><strong>Market Mood: {{ mood.label }}</strong> (score {{ mood.score }})</p>
  {% if mood.headlines %}
  <ul class="muted">
    {% for h in mood.headlines %}<li>{{ h.title }} <span class="muted">({{ h.source }})</span></li>{% endfor %}
  </ul>
  {% endif %}
</div>
```

Reuses the existing `.card`/`.muted` classes — no new CSS needed.

## Error handling

- Individual feed fetch/parse failure: skip that feed, continue with the
  rest (`fetch_headlines` never raises for a single bad feed).
- All feeds failing, or any unexpected exception in the mood pipeline:
  `get_or_fetch_daily_mood` catches it and returns the neutral/"Unavailable"
  shape. Recommendations generation must never fail or block because news
  fetching failed — this mirrors the existing `InsufficientData`/
  channel-unavailable graceful-degradation style elsewhere in the app.
- Mood is computed and cached once per calendar day (`generated_date`),
  matching how `downloads_log` avoids re-fetching a day already recorded.

## Testing approach

- `tests/test_news.py`: `score_mood` unit tests (clear bullish set, clear
  bearish set, mixed/neutral set, empty list -> "Unavailable"), and
  `fetch_headlines` tests using an injected `fetch_fn` returning canned RSS
  XML strings (one feed succeeds, one raises -> result still contains the
  successful feed's headlines).
- `get_or_fetch_daily_mood` tests: first call stores a row and returns it;
  second call for the same date returns the stored row without calling
  `fetch_fn` again (cache/idempotency, same pattern as existing
  `download_missing_days` tests).
- `tests/test_recommender.py` additions: a buy pick with `mood_score=+1.0`
  gets a wider stop-loss than the same pick with `mood_score=0.0`; a sell
  pick with `mood_score=+1.0` (mood disagrees with a sell) gets a *tighter*
  stop-loss. Target is asserted unchanged across all mood values.
- `tests/test_integration.py` addition: `/recommendations` response body
  contains the mood label/banner.

## Explicitly out of scope

Per-stock news matching, changing symbol selection/ranking, changing
targets, ML/sentiment models, historical mood backfill for past dates.
