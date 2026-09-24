from datetime import date, timedelta

import pytest

from nse_recommender import recommender
from nse_recommender.db import get_connection, init_db

DATES = [date(2024, 1, 1) + timedelta(days=i) for i in range(11)]
SYMBOLS = [f"SYM{i:02d}" for i in range(12)]
FINAL_RETURNS = {SYMBOLS[i]: (i - 5) * 0.02 for i in range(12)}  # -0.10 .. +0.12


def _close_at(symbol, date_index):
    ret = FINAL_RETURNS[symbol]
    return 100 * (1 + ret * (date_index / 10))


@pytest.fixture
def seeded_conn():
    conn = get_connection(":memory:")
    init_db(conn)
    rows = []
    for date_index, d in enumerate(DATES):
        for symbol in SYMBOLS:
            close = _close_at(symbol, date_index)
            rows.append({
                "symbol": symbol, "date": d.isoformat(), "open": close, "high": close,
                "low": close, "close": close, "volume": 1000,
            })
    conn.executemany(
        """INSERT INTO bhavcopy_prices (symbol, date, open, high, low, close, volume)
           VALUES (:symbol, :date, :open, :high, :low, :close, :volume)""",
        rows,
    )
    conn.commit()
    return conn


def test_compute_returns_ranks_symbols_by_pct_change(seeded_conn):
    ranked = recommender.compute_returns(seeded_conn, SYMBOLS, lookback_days=10)
    assert ranked.iloc[0]["symbol"] == "SYM11"
    assert ranked.iloc[-1]["symbol"] == "SYM00"


def test_compute_returns_raises_when_not_enough_history(seeded_conn):
    with pytest.raises(recommender.InsufficientData) as excinfo:
        recommender.compute_returns(seeded_conn, SYMBOLS, lookback_days=40)
    assert excinfo.value.have == 11
    assert excinfo.value.need == 41


def test_generate_recommendations_short_term_returns_top5_buy_and_bottom5_sell(seeded_conn):
    result = recommender.generate_recommendations(seeded_conn, SYMBOLS, "short_term")
    assert result["status"] == "ok"
    assert [p["symbol"] for p in result["buy"]] == ["SYM11", "SYM10", "SYM09", "SYM08", "SYM07"]
    assert [p["symbol"] for p in result["sell"]] == ["SYM00", "SYM01", "SYM02", "SYM03", "SYM04"]


def test_generate_recommendations_buy_pick_target_and_stop_loss(seeded_conn):
    result = recommender.generate_recommendations(seeded_conn, SYMBOLS, "short_term")
    top_pick = result["buy"][0]
    entry = top_pick["entry"]
    assert top_pick["target"] == round(entry * 1.05, 2)
    assert top_pick["stop_loss"] == round(entry * 0.975, 2)


def test_generate_recommendations_picks_include_streak_info(seeded_conn):
    result = recommender.generate_recommendations(seeded_conn, SYMBOLS, "short_term")
    # SYM11's close rises every single day across all 11 seeded dates, so its
    # streak should be a 10-day up run starting from the very first date.
    top_buy_streak = result["buy"][0]["streak"]
    assert top_buy_streak["direction"] == "up"
    assert top_buy_streak["length"] == 10
    assert top_buy_streak["start_date"] == DATES[0].isoformat()
    # SYM00's close falls every single day, so its streak is a down run.
    top_sell_streak = result["sell"][0]["streak"]
    assert top_sell_streak["direction"] == "down"
    assert top_sell_streak["length"] == 10


def test_generate_recommendations_sell_pick_target_below_entry(seeded_conn):
    result = recommender.generate_recommendations(seeded_conn, SYMBOLS, "short_term")
    top_sell = result["sell"][0]
    assert top_sell["target"] < top_sell["entry"] < top_sell["stop_loss"]


def test_generate_recommendations_long_term_reports_insufficient_data(seeded_conn):
    result = recommender.generate_recommendations(seeded_conn, SYMBOLS, "long_term")
    assert result["status"] == "insufficient_data"
    assert result["have"] == 11
    assert result["need"] == 41
    assert "label" in result


def test_symbol_momentum_returns_ok_for_a_symbol_with_enough_history(seeded_conn):
    result = recommender.symbol_momentum(seeded_conn, "SYM11", "short_term")
    assert result["status"] == "ok"
    assert result["reason"] == "+3.3% over last 3 trading days"
    assert result["entry_date"] == DATES[-1].isoformat()


def test_symbol_momentum_returns_insufficient_data_for_long_term(seeded_conn):
    result = recommender.symbol_momentum(seeded_conn, "SYM11", "long_term")
    assert result["status"] == "insufficient_data"
    assert result["have"] == 11
    assert result["need"] == 41


def test_symbol_momentum_returns_insufficient_data_for_unknown_symbol(seeded_conn):
    result = recommender.symbol_momentum(seeded_conn, "NOTREAL", "short_term")
    assert result["status"] == "insufficient_data"


def test_generate_and_save_all_persists_ok_horizons_only(seeded_conn):
    recommender.generate_and_save_all(seeded_conn, SYMBOLS, generated_date="2024-01-11")
    rows = seeded_conn.execute("SELECT DISTINCT horizon FROM recommendations").fetchall()
    horizons_saved = {r["horizon"] for r in rows}
    assert horizons_saved == {"short_term", "mid_term"}


def test_generate_recommendations_picks_include_entry_date(seeded_conn):
    result = recommender.generate_recommendations(seeded_conn, SYMBOLS, "short_term")
    assert result["buy"][0]["entry_date"] == DATES[-1].isoformat()
    assert result["sell"][0]["entry_date"] == DATES[-1].isoformat()


def test_save_recommendations_persists_entry_date(seeded_conn):
    recommender.generate_and_save_all(seeded_conn, SYMBOLS, generated_date="2024-01-11")
    row = seeded_conn.execute(
        "SELECT entry_date FROM recommendations WHERE horizon = 'short_term' LIMIT 1"
    ).fetchone()
    assert row["entry_date"] == DATES[-1].isoformat()


def test_generate_and_save_all_is_idempotent_on_repeat_calls(seeded_conn):
    # Regression test for C1: calling generate_and_save_all twice with the
    # same generated_date must not duplicate rows (INSERT OR IGNORE + the
    # UNIQUE constraint on (symbol, horizon, side, generated_date)).
    recommender.generate_and_save_all(seeded_conn, SYMBOLS, generated_date="2024-01-11")
    recommender.generate_and_save_all(seeded_conn, SYMBOLS, generated_date="2024-01-11")
    count = seeded_conn.execute("SELECT COUNT(*) AS c FROM recommendations").fetchone()["c"]
    # 2 horizons (short_term, mid_term) ok x 2 sides x 5 picks each = 20 rows total.
    assert count == 20
