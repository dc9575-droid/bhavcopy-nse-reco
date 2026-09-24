from datetime import date, timedelta

from nse_recommender import outcomes
from nse_recommender.db import get_connection, init_db


def _insert_price(conn, symbol, d, close):
    conn.execute(
        "INSERT INTO bhavcopy_prices (symbol, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
        (symbol, d.isoformat(), close, close, close, close, 1000),
    )
    conn.commit()


def _insert_recommendation(
    conn, symbol, side, generated_date, entry, target, stop_loss, entry_date=None, horizon="short_term"
):
    conn.execute(
        """INSERT INTO recommendations
           (symbol, horizon, side, generated_date, entry_date, entry, target, stop_loss)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (symbol, horizon, side, generated_date, entry_date or generated_date, entry, target, stop_loss),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM recommendations WHERE symbol = ?", (symbol,)).fetchone())


def test_compute_outcome_detects_target_hit_for_buy_pick():
    conn = get_connection(":memory:")
    init_db(conn)
    base = date(2026, 1, 1)
    rec = _insert_recommendation(conn, "RELIANCE", "buy", base.isoformat(), 100, 105, 95)
    _insert_price(conn, "RELIANCE", base + timedelta(days=1), 102)
    _insert_price(conn, "RELIANCE", base + timedelta(days=2), 106)
    outcome = outcomes.compute_outcome(conn, rec)
    assert outcome["status"] == "target_hit"
    assert outcome["current_price"] == 106


def test_compute_outcome_detects_stop_loss_hit_for_buy_pick():
    conn = get_connection(":memory:")
    init_db(conn)
    base = date(2026, 1, 1)
    rec = _insert_recommendation(conn, "RELIANCE", "buy", base.isoformat(), 100, 105, 95)
    _insert_price(conn, "RELIANCE", base + timedelta(days=1), 94)
    outcome = outcomes.compute_outcome(conn, rec)
    assert outcome["status"] == "stop_loss_hit"


def test_compute_outcome_still_open_with_no_later_data():
    conn = get_connection(":memory:")
    init_db(conn)
    base = date(2026, 1, 1)
    rec = _insert_recommendation(conn, "RELIANCE", "buy", base.isoformat(), 100, 105, 95)
    outcome = outcomes.compute_outcome(conn, rec)
    assert outcome["status"] == "still_open"
    assert outcome["current_price"] == 100


def test_compute_outcome_still_open_with_later_data_between_bands():
    conn = get_connection(":memory:")
    init_db(conn)
    base = date(2026, 1, 1)
    rec = _insert_recommendation(conn, "RELIANCE", "buy", base.isoformat(), 100, 105, 95)
    _insert_price(conn, "RELIANCE", base + timedelta(days=1), 101)
    outcome = outcomes.compute_outcome(conn, rec)
    assert outcome["status"] == "still_open"
    assert outcome["current_price"] == 101


def test_compute_outcome_sell_pick_target_is_price_falling():
    conn = get_connection(":memory:")
    init_db(conn)
    base = date(2026, 1, 1)
    rec = _insert_recommendation(conn, "TCS", "sell", base.isoformat(), 100, 90, 110)
    _insert_price(conn, "TCS", base + timedelta(days=1), 89)
    outcome = outcomes.compute_outcome(conn, rec)
    assert outcome["status"] == "target_hit"


def test_compute_outcome_uses_entry_date_not_generated_date():
    # Regression test for I4: generated_date is the wall-clock date the pick
    # was created, but entry_date is the date the entry price actually came
    # from (can be meaningfully earlier, e.g. weekends/late downloads). A bar
    # strictly between entry_date and generated_date must still be scanned.
    conn = get_connection(":memory:")
    init_db(conn)
    entry_date = date(2026, 1, 1)
    generated_date = date(2026, 1, 5)  # generated several days after entry_date
    rec = _insert_recommendation(
        conn, "RELIANCE", "buy", generated_date.isoformat(), 100, 105, 95,
        entry_date=entry_date.isoformat(),
    )
    # This bar falls between entry_date and generated_date; with the old bug
    # (filtering on generated_date) it would be silently skipped.
    _insert_price(conn, "RELIANCE", entry_date + timedelta(days=2), 106)
    outcome = outcomes.compute_outcome(conn, rec)
    assert outcome["status"] == "target_hit"
    assert outcome["current_price"] == 106


def test_compute_outcome_still_open_with_multiple_later_rows_never_hitting_either_band():
    conn = get_connection(":memory:")
    init_db(conn)
    base = date(2026, 1, 1)
    rec = _insert_recommendation(conn, "RELIANCE", "buy", base.isoformat(), 100, 105, 95)
    _insert_price(conn, "RELIANCE", base + timedelta(days=1), 101)
    _insert_price(conn, "RELIANCE", base + timedelta(days=2), 99)
    _insert_price(conn, "RELIANCE", base + timedelta(days=3), 103)
    outcome = outcomes.compute_outcome(conn, rec)
    assert outcome["status"] == "still_open"
    assert outcome["as_of_date"] == (base + timedelta(days=3)).isoformat()
    assert outcome["current_price"] == 103


def test_list_past_picks_orders_most_recent_first():
    conn = get_connection(":memory:")
    init_db(conn)
    _insert_recommendation(conn, "OLD", "buy", "2026-01-01", 100, 105, 95)
    _insert_recommendation(conn, "NEW", "buy", "2026-02-01", 100, 105, 95)
    picks = outcomes.list_past_picks(conn)
    assert [p["symbol"] for p in picks] == ["NEW", "OLD"]


def test_period_start_short_term_is_the_generated_date_itself():
    d = date(2026, 9, 23)
    assert outcomes.period_start("short_term", d) == d


def test_period_start_mid_term_is_the_monday_of_that_week():
    # 2026-09-23 is a Wednesday; Monday of that week is 2026-09-21.
    assert outcomes.period_start("mid_term", date(2026, 9, 23)) == date(2026, 9, 21)
    # A Monday maps to itself.
    assert outcomes.period_start("mid_term", date(2026, 9, 21)) == date(2026, 9, 21)


def test_period_start_long_term_is_a_14_day_bucket_that_spans_two_mid_term_weeks():
    # 2026-09-21 and 2026-09-23 fall in the same mid-term week (Monday 09-21)
    # AND the same long-term 14-day bucket (also starting 09-21).
    assert outcomes.period_start("long_term", date(2026, 9, 21)) == date(2026, 9, 21)
    assert outcomes.period_start("long_term", date(2026, 9, 23)) == date(2026, 9, 21)
    # 2026-09-28 is a different mid-term week (Monday 09-28) but the SAME
    # long-term bucket as 09-21/09-23 (long-term buckets span two weeks).
    assert outcomes.period_start("mid_term", date(2026, 9, 28)) == date(2026, 9, 28)
    assert outcomes.period_start("long_term", date(2026, 9, 28)) == date(2026, 9, 21)
    # 2026-10-05 is far enough ahead to land in the next long-term bucket.
    assert outcomes.period_start("long_term", date(2026, 10, 5)) == date(2026, 10, 5)


def test_period_start_unknown_horizon_raises():
    import pytest

    with pytest.raises(ValueError):
        outcomes.period_start("bogus", date(2026, 9, 23))


def test_daily_results_groups_short_term_picks_by_day():
    conn = get_connection(":memory:")
    init_db(conn)
    base = date(2026, 9, 23)
    # Day 1: one target hit, one stop-loss hit.
    _insert_recommendation(conn, "AAA", "buy", base.isoformat(), 100, 105, 95, horizon="short_term")
    _insert_price(conn, "AAA", base + timedelta(days=1), 106)
    _insert_recommendation(conn, "BBB", "buy", base.isoformat(), 100, 105, 95, horizon="short_term")
    _insert_price(conn, "BBB", base + timedelta(days=1), 94)
    # Day 2: one still open.
    day2 = base + timedelta(days=1)
    _insert_recommendation(conn, "CCC", "buy", day2.isoformat(), 100, 105, 95, horizon="short_term")

    results = outcomes.daily_results(conn)
    short = {row["period_start"]: row for row in results["short_term"]}

    assert short[base.isoformat()]["target_hit"] == 1
    assert short[base.isoformat()]["stop_loss_hit"] == 1
    assert short[base.isoformat()]["still_open"] == 0
    assert short[base.isoformat()]["total"] == 2
    assert short[base.isoformat()]["win_rate"] == 50

    assert short[day2.isoformat()]["still_open"] == 1
    assert short[day2.isoformat()]["win_rate"] is None  # nothing resolved yet


def test_daily_results_groups_mid_and_long_term_by_their_own_cadence():
    conn = get_connection(":memory:")
    init_db(conn)
    # These two generated_dates are the same mid-term week AND the same
    # long-term 14-day bucket (see the period_start tests above).
    _insert_recommendation(conn, "AAA", "buy", "2026-09-21", 100, 105, 95, horizon="mid_term")
    _insert_recommendation(conn, "BBB", "buy", "2026-09-23", 100, 105, 95, horizon="mid_term")
    # This one is a different mid-term week but the SAME long-term bucket.
    _insert_recommendation(conn, "CCC", "buy", "2026-09-28", 100, 105, 95, horizon="long_term")
    _insert_recommendation(conn, "DDD", "buy", "2026-09-21", 100, 105, 95, horizon="long_term")

    results = outcomes.daily_results(conn)
    mid = {row["period_start"]: row for row in results["mid_term"]}
    long_ = {row["period_start"]: row for row in results["long_term"]}

    # Mid-term: both AAA and BBB fall in the same Monday-anchored week.
    assert mid["2026-09-21"]["total"] == 2
    assert mid["2026-09-21"]["period_label"] == "Week of 2026-09-21"

    # Long-term: CCC (09-28) and DDD (09-21) fall in the SAME 14-day bucket,
    # unlike mid-term where they'd be in different weeks.
    assert long_["2026-09-21"]["total"] == 2
    assert long_["2026-09-21"]["period_label"] == "2026-09-21 to 2026-10-04"


def test_daily_results_sorts_periods_most_recent_first():
    conn = get_connection(":memory:")
    init_db(conn)
    _insert_recommendation(conn, "OLD", "buy", "2026-09-01", 100, 105, 95, horizon="short_term")
    _insert_recommendation(conn, "NEW", "buy", "2026-09-23", 100, 105, 95, horizon="short_term")

    results = outcomes.daily_results(conn)
    periods = [row["period_start"] for row in results["short_term"]]
    assert periods == ["2026-09-23", "2026-09-01"]


_SAMPLE_PICKS = [
    {"symbol": "AAA", "horizon": "short_term", "generated_date": "2026-09-23", "status": "target_hit"},
    {"symbol": "BBB", "horizon": "short_term", "generated_date": "2026-09-23", "status": "stop_loss_hit"},
    {"symbol": "CCC", "horizon": "short_term", "generated_date": "2026-09-22", "status": "stop_loss_hit"},
    {"symbol": "DDD", "horizon": "mid_term", "generated_date": "2026-09-23", "status": "still_open"},
]


def test_filter_picks_with_no_filters_returns_everything():
    assert outcomes.filter_picks(_SAMPLE_PICKS) == _SAMPLE_PICKS


def test_filter_picks_by_status_only():
    result = outcomes.filter_picks(_SAMPLE_PICKS, status="stop_loss_hit")
    assert [p["symbol"] for p in result] == ["BBB", "CCC"]


def test_filter_picks_by_horizon_only():
    result = outcomes.filter_picks(_SAMPLE_PICKS, horizon="mid_term")
    assert [p["symbol"] for p in result] == ["DDD"]


def test_filter_picks_by_horizon_period_and_status_combined():
    # BBB and CCC are both short_term/stop_loss_hit, but only BBB's
    # generated_date (2026-09-23) falls in the 2026-09-23 short-term period
    # (short-term periods are per-day, so CCC's 09-22 pick is excluded).
    result = outcomes.filter_picks(
        _SAMPLE_PICKS, horizon="short_term", period="2026-09-23", status="stop_loss_hit"
    )
    assert [p["symbol"] for p in result] == ["BBB"]
