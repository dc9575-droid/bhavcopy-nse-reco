from datetime import date, timedelta

from nse_recommender import outcomes
from nse_recommender.db import get_connection, init_db


def _insert_price(conn, symbol, d, close):
    conn.execute(
        "INSERT INTO bhavcopy_prices (symbol, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
        (symbol, d.isoformat(), close, close, close, close, 1000),
    )
    conn.commit()


def _insert_recommendation(conn, symbol, side, generated_date, entry, target, stop_loss, entry_date=None):
    conn.execute(
        """INSERT INTO recommendations
           (symbol, horizon, side, generated_date, entry_date, entry, target, stop_loss)
           VALUES (?, 'short_term', ?, ?, ?, ?, ?, ?)""",
        (symbol, side, generated_date, entry_date or generated_date, entry, target, stop_loss),
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
