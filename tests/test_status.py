from datetime import date

from nse_recommender import status
from nse_recommender.db import get_connection, init_db


def _insert_price(conn, symbol, d):
    conn.execute(
        "INSERT INTO bhavcopy_prices (symbol, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
        (symbol, d.isoformat(), 100, 100, 100, 100, 1000),
    )


def test_coverage_summary_with_no_data():
    conn = get_connection(":memory:")
    init_db(conn)
    summary = status.coverage_summary(conn, date(2024, 1, 16))
    assert summary["earliest_date"] is None
    assert summary["latest_date"] is None
    assert summary["total_days"] == 0
    assert summary["ranges"]["yesterday"] == {"expected": 1, "present": 0}


def test_coverage_summary_reflects_downloaded_and_holiday_days():
    conn = get_connection(":memory:")
    init_db(conn)
    today = date(2024, 1, 16)  # Tuesday; yesterday = Monday Jan 15
    _insert_price(conn, "RELIANCE", date(2024, 1, 15))
    conn.execute(
        "INSERT INTO downloads_log (date, status, message, fetched_at) VALUES (?,?,?,?)",
        ("2024-01-12", "no_data", None, "2024-01-16T00:00:00"),
    )
    conn.commit()

    summary = status.coverage_summary(conn, today)

    assert summary["earliest_date"] == "2024-01-15"
    assert summary["latest_date"] == "2024-01-15"
    assert summary["total_days"] == 1
    assert summary["ranges"]["yesterday"] == {"expected": 1, "present": 1}
    # this_month candidate weekdays: Jan 1-5, 8-12, 15, 16 = 12 weekdays;
    # Jan 12 confirmed no_data (holiday) -> expected = 11; only Jan 15 present.
    assert summary["ranges"]["this_month"] == {"expected": 11, "present": 1}
