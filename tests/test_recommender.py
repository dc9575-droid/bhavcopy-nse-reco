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


def test_generate_and_save_all_persists_ok_horizons_only(seeded_conn):
    recommender.generate_and_save_all(seeded_conn, SYMBOLS, generated_date="2024-01-11")
    rows = seeded_conn.execute("SELECT DISTINCT horizon FROM recommendations").fetchall()
    horizons_saved = {r["horizon"] for r in rows}
    assert horizons_saved == {"short_term", "mid_term"}
