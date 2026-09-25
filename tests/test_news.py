import json
from datetime import date

from nse_recommender import news
from nse_recommender.db import get_connection, init_db


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


def test_score_mood_does_not_match_lexicon_words_as_substrings():
    # "boombox" contains "boom" as a substring but is not the word "boom" --
    # whole-word matching must not count it. Naive substring matching would
    # incorrectly score this as positive.
    headlines = [{"title": "New boombox launches at retail stores", "source": "BBC", "category": "international"}]
    result = news.score_mood(headlines)
    assert result["score"] == 0.0
    assert result["label"] == "Neutral"


def test_score_mood_denominator_excludes_non_matching_headlines_for_a_decisive_signal():
    """Regression test for the dilution fix: the denominator must count only
    headlines that matched the lexicon, not every fetched headline. In
    production ~100 headlines are fetched per day (one of the three feeds is
    general world news) but usually only a couple ever contain a lexicon
    word. Dividing by the total headline count buries any real signal near
    zero and makes the +-0.3 Bullish/Bearish thresholds practically
    unreachable. This mirrors a realistic "20 neutral headlines + 2 clearly
    negative ones" shape.
    """
    neutral_headlines = [
        {"title": f"Markets trade range-bound in session number {i}", "source": "ET", "category": "national"}
        for i in range(20)
    ]
    negative_headlines = [
        {"title": "Markets crash amid weak earnings outlook", "source": "ET", "category": "national"},
        {"title": "Stocks plunge on renewed global weakness", "source": "BS", "category": "national"},
    ]
    headlines = neutral_headlines + negative_headlines  # 22 headlines total
    result = news.score_mood(headlines)

    # Hand computation:
    # positive_hits = 0, negative_hits = 2 ("crash", "plunge") -- 22 headlines total.
    # OLD formula (diluted by ALL headlines): (0 - 2) / 22 = -0.0909... -> rounds
    # to -0.091, which stays inside the +-0.3 "Neutral" band -- the real signal
    # would have been invisible under the old formula.
    old_formula_score = round((0 - 2) / len(headlines), 3)
    assert old_formula_score == -0.091

    # NEW formula (diluted only by matched headlines): (0 - 2) / max(0 + 2, 1) = -1.0,
    # clamped to -1.0 -- clearly crosses the -0.3 threshold into "Bearish".
    assert result["score"] == -1.0
    assert result["label"] == "Bearish"
    assert abs(result["score"]) > abs(old_formula_score)


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


def test_get_or_fetch_daily_mood_degrades_to_neutral_when_database_fails():
    """Verifies that any exception during fetch-score-store (including DB failures)
    is swallowed and returns neutral/"Unavailable" result instead of propagating."""
    conn = get_connection(":memory:")
    init_db(conn)

    def fake_fetch(url):
        return SAMPLE_FEED_XML

    # Wrapper connection that raises on commit, simulating DB failure
    class FailingConnection:
        def __init__(self, real_conn):
            self.real_conn = real_conn

        def execute(self, sql, params=None):
            return self.real_conn.execute(sql, params) if params else self.real_conn.execute(sql)

        def commit(self):
            raise RuntimeError("simulated database error")

        def fetchone(self):
            return self.real_conn.fetchone()

    # Even though conn.commit() raises, get_or_fetch_daily_mood must swallow the
    # exception and return the neutral/"Unavailable" result
    failing_conn = FailingConnection(conn)
    mood = news.get_or_fetch_daily_mood(failing_conn, date(2026, 9, 25), fetch_fn=fake_fetch)
    assert mood["score"] == 0.0
    assert mood["label"] == "Unavailable"
    assert mood["headlines"] == []


def test_get_or_fetch_daily_mood_degrades_to_neutral_when_cache_read_fails():
    """Verifies that a DB error on the cache-lookup SELECT itself (not just
    the later write) is also swallowed and returns the neutral/"Unavailable"
    result instead of propagating -- the try block must wrap the cache read
    too, not just the fetch-score-store sequence."""

    calls = {"n": 0}

    def fetch_fn_that_should_never_run(url):
        # If the SELECT's exception isn't caught before we reach the fetch
        # step, this would be called -- it shouldn't be.
        calls["n"] += 1
        return SAMPLE_FEED_XML

    # Fake connection that raises as soon as the cache-lookup SELECT runs.
    class FailingSelectConnection:
        def execute(self, sql, params=None):
            raise RuntimeError("simulated database error on cache read")

    failing_conn = FailingSelectConnection()
    mood = news.get_or_fetch_daily_mood(
        failing_conn, date(2026, 9, 25), fetch_fn=fetch_fn_that_should_never_run
    )
    assert mood["score"] == 0.0
    assert mood["label"] == "Unavailable"
    assert mood["headlines"] == []
    assert calls["n"] == 0  # failed before ever reaching fetch_headlines
