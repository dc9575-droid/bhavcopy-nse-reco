from datetime import date, timedelta

from nse_recommender import channel
from nse_recommender.db import get_connection, init_db


def _insert_price(conn, symbol, d, close):
    conn.execute(
        "INSERT INTO bhavcopy_prices (symbol, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
        (symbol, d.isoformat(), close, close, close, close, 1000),
    )
    conn.commit()


def _seed(conn, symbol, closes, start=date(2026, 9, 1)):
    for i, close in enumerate(closes):
        _insert_price(conn, symbol, start + timedelta(days=i), close)


NOISY_UPTREND = [
    100, 102, 101, 104, 103, 106, 105, 108, 107, 110,
    109, 112, 111, 114, 113, 116, 115, 118, 117, 120,
]


def test_compute_channel_fits_a_regression_line_and_bands():
    # Exact expected values independently verified via numpy.polyfit on this
    # same series before writing this test (see session notes): slope~1.0,
    # centerline~119.06, population-std residuals~0.97, k=2 bands.
    conn = get_connection(":memory:")
    init_db(conn)
    _seed(conn, "AAA", NOISY_UPTREND)

    result = channel.compute_channel(conn, "AAA")

    assert result["available"] is True
    assert result["support"] == 117.11
    assert result["resistance"] == 121.0
    assert result["centerline"] == 119.06
    assert result["current_price"] == 120.0
    assert result["position_pct"] == 74.2
    assert result["label"] == "74% of 117.11-121.0"
    assert round(result["resid_std"], 4) == 0.9734
    assert len(result["points"]) == 20
    assert result["points"][0]["date"] == date(2026, 9, 1).isoformat()
    assert result["points"][0]["close"] == 100
    assert round(result["points"][0]["fitted"], 2) == 100.04
    assert result["points"][-1]["date"] == date(2026, 9, 20).isoformat()
    assert result["points"][-1]["close"] == 120
    assert round(result["points"][-1]["fitted"], 2) == 119.06
    # One-step-ahead linear extrapolation of the SAME fitted trend line --
    # not a prediction of where price will actually go, just where the
    # existing line/band would sit if extended by one more day.
    assert result["next_centerline"] == 120.06
    assert result["next_support"] == 118.11
    assert result["next_resistance"] == 122.0


def test_compute_channel_perfectly_linear_data_has_zero_width_band():
    conn = get_connection(":memory:")
    init_db(conn)
    _seed(conn, "BBB", [100 + 2 * i for i in range(20)])  # exactly on a line

    result = channel.compute_channel(conn, "BBB")

    assert result["available"] is True
    assert result["support"] == result["resistance"] == result["centerline"] == 138.0
    # Zero-width band: current price sits exactly on the line, define as 50%
    # rather than dividing by zero.
    assert result["position_pct"] == 50.0


def test_compute_channel_unavailable_with_insufficient_history():
    conn = get_connection(":memory:")
    init_db(conn)
    _seed(conn, "CCC", [100, 101, 102])  # far fewer than the 20-day window

    result = channel.compute_channel(conn, "CCC")

    assert result["available"] is False
    assert result["have"] == 3
    assert result["need"] == 20


def test_compute_channel_unavailable_with_no_data_at_all():
    conn = get_connection(":memory:")
    init_db(conn)

    result = channel.compute_channel(conn, "DDD")

    assert result["available"] is False
    assert result["have"] == 0
    assert result["need"] == 20


def test_compute_channel_uses_only_the_trailing_window_not_older_history():
    conn = get_connection(":memory:")
    init_db(conn)
    # 10 flat days at 50 (would drag the fit if included), then the same
    # 20-day noisy uptrend used in the main test above.
    _seed(conn, "EEE", [50] * 10, start=date(2026, 8, 1))
    _seed(conn, "EEE", NOISY_UPTREND, start=date(2026, 9, 1))

    result = channel.compute_channel(conn, "EEE")

    # Must match the main test's numbers exactly -- the older flat data must
    # not have influenced the fit.
    assert result["support"] == 117.11
    assert result["resistance"] == 121.0
    assert result["centerline"] == 119.06
