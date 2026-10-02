from datetime import date, timedelta

from nse_recommender import performance
from nse_recommender.db import get_connection, init_db


def _insert_price(conn, symbol, d, close):
    conn.execute(
        "INSERT INTO bhavcopy_prices (symbol, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
        (symbol, d.isoformat(), close, close, close, close, 1000),
    )
    conn.commit()


def _insert_recommendation(
    conn, symbol, side, horizon, generated_date, entry, target, stop_loss,
    streak_direction=None, streak_length=None, channel_position_pct=None,
):
    conn.execute(
        """INSERT INTO recommendations
           (symbol, horizon, side, generated_date, entry_date, entry, target, stop_loss,
            streak_direction, streak_length, channel_position_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            symbol, horizon, side, generated_date, generated_date, entry, target, stop_loss,
            streak_direction, streak_length, channel_position_pct,
        ),
    )
    conn.commit()


def test_win_rate_by_segment_groups_by_horizon_and_side():
    conn = get_connection(":memory:")
    init_db(conn)
    base = date(2026, 1, 1)
    _insert_recommendation(conn, "AAA", "buy", "short_term", base.isoformat(), 100, 105, 95)
    _insert_price(conn, "AAA", base + timedelta(days=1), 106)  # target hit
    _insert_recommendation(conn, "BBB", "buy", "short_term", base.isoformat(), 100, 105, 95)
    _insert_price(conn, "BBB", base + timedelta(days=1), 94)  # stop loss hit

    result = performance.win_rate_by_segment(conn)
    row = next(r for r in result["by_horizon_side"] if r["label"] == "short_term / buy")
    assert row["target_hit"] == 1
    assert row["stop_loss_hit"] == 1
    assert row["total"] == 2
    assert row["win_rate"] == 50
    # Structured fields (not just the composed label) so templates can link
    # a row straight to a Past Picks filter without parsing the label string.
    assert row["horizon"] == "short_term"
    assert row["side"] == "buy"


def test_win_rate_by_segment_excludes_still_open_picks():
    conn = get_connection(":memory:")
    init_db(conn)
    base = date(2026, 1, 1)
    _insert_recommendation(conn, "AAA", "buy", "short_term", base.isoformat(), 100, 105, 95)
    # No later price at all -> still_open, must not appear in any segment.
    result = performance.win_rate_by_segment(conn)
    assert result["by_horizon_side"] == []


def test_win_rate_by_segment_groups_by_streak_direction_at_entry():
    conn = get_connection(":memory:")
    init_db(conn)
    base = date(2026, 1, 1)
    _insert_recommendation(
        conn, "AAA", "buy", "short_term", base.isoformat(), 100, 105, 95,
        streak_direction="up", streak_length=5,
    )
    _insert_price(conn, "AAA", base + timedelta(days=1), 106)  # target hit
    _insert_recommendation(
        conn, "BBB", "buy", "short_term", base.isoformat(), 100, 105, 95,
        streak_direction="down", streak_length=3,
    )
    _insert_price(conn, "BBB", base + timedelta(days=1), 94)  # stop loss hit

    result = performance.win_rate_by_segment(conn)
    up_row = next(r for r in result["by_streak_direction"] if r["label"] == "up")
    down_row = next(r for r in result["by_streak_direction"] if r["label"] == "down")
    assert up_row["target_hit"] == 1 and up_row["stop_loss_hit"] == 0
    assert down_row["target_hit"] == 0 and down_row["stop_loss_hit"] == 1


def test_win_rate_by_segment_ignores_picks_missing_streak_direction():
    conn = get_connection(":memory:")
    init_db(conn)
    base = date(2026, 1, 1)
    _insert_recommendation(conn, "AAA", "buy", "short_term", base.isoformat(), 100, 105, 95)
    _insert_price(conn, "AAA", base + timedelta(days=1), 106)
    result = performance.win_rate_by_segment(conn)
    assert result["by_streak_direction"] == []


def test_win_rate_by_segment_buckets_channel_position_at_entry():
    conn = get_connection(":memory:")
    init_db(conn)
    base = date(2026, 1, 1)
    _insert_recommendation(
        conn, "AAA", "buy", "short_term", base.isoformat(), 100, 105, 95,
        channel_position_pct=60.0,
    )
    _insert_price(conn, "AAA", base + timedelta(days=1), 106)  # target hit, below support
    _insert_recommendation(
        conn, "BBB", "buy", "short_term", base.isoformat(), 100, 105, 95,
        channel_position_pct=90.0,
    )
    _insert_price(conn, "BBB", base + timedelta(days=1), 94)  # stop loss hit, within channel
    _insert_recommendation(
        conn, "CCC", "buy", "short_term", base.isoformat(), 100, 105, 95,
        channel_position_pct=115.0,
    )
    _insert_price(conn, "CCC", base + timedelta(days=1), 106)  # target hit, broken above

    result = performance.win_rate_by_segment(conn)
    labels = {r["label"] for r in result["by_channel_position"]}
    assert labels == {"Below support (<80%)", "Within channel (80-100%)", "Broken above (>100%)"}
    below = next(r for r in result["by_channel_position"] if r["label"] == "Below support (<80%)")
    assert below["target_hit"] == 1
    assert below["stop_loss_hit"] == 0


def test_win_rate_by_segment_ignores_picks_missing_channel_position():
    conn = get_connection(":memory:")
    init_db(conn)
    base = date(2026, 1, 1)
    _insert_recommendation(conn, "AAA", "buy", "short_term", base.isoformat(), 100, 105, 95)
    _insert_price(conn, "AAA", base + timedelta(days=1), 106)
    result = performance.win_rate_by_segment(conn)
    assert result["by_channel_position"] == []


def _row(label, target_hit, stop_loss_hit, horizon=None, side=None):
    total = target_hit + stop_loss_hit
    return {
        "label": label, "horizon": horizon, "side": side,
        "target_hit": target_hit, "stop_loss_hit": stop_loss_hit,
        "total": total, "win_rate": round(100 * target_hit / total) if total else None,
    }


def test_horizon_narratives_names_the_stronger_side_when_sell_wins():
    by_horizon_side = [
        _row("short_term / buy", 5, 34, horizon="short_term", side="buy"),   # 13%
        _row("short_term / sell", 19, 5, horizon="short_term", side="sell"),  # 79%
    ]
    narratives = performance.horizon_narratives(by_horizon_side)
    text = narratives["short_term"]
    assert "SELL" in text and "79%" in text
    assert "BUY" in text and "13%" in text


def test_horizon_narratives_names_the_stronger_side_when_buy_wins():
    by_horizon_side = [
        _row("mid_term / buy", 14, 2, horizon="mid_term", side="buy"),    # 88%
        _row("mid_term / sell", 1, 17, horizon="mid_term", side="sell"),  # 6%
    ]
    narratives = performance.horizon_narratives(by_horizon_side)
    text = narratives["mid_term"]
    assert "BUY" in text and "88%" in text
    assert "SELL" in text and "6%" in text


def test_horizon_narratives_handles_an_equal_win_rate():
    by_horizon_side = [
        _row("short_term / buy", 5, 5, horizon="short_term", side="buy"),
        _row("short_term / sell", 5, 5, horizon="short_term", side="sell"),
    ]
    narratives = performance.horizon_narratives(by_horizon_side)
    assert "50%" in narratives["short_term"]


def test_horizon_narratives_handles_only_one_side_resolved():
    by_horizon_side = [
        _row("long_term / buy", 3, 1, horizon="long_term", side="buy"),  # 75%
    ]
    narratives = performance.horizon_narratives(by_horizon_side)
    text = narratives["long_term"]
    assert "BUY" in text
    assert "75%" in text
    assert "SELL" not in text


def test_horizon_narratives_omits_a_horizon_with_no_resolved_picks():
    narratives = performance.horizon_narratives([])
    assert narratives == {}
