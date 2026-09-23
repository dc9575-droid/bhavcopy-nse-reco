import sqlite3

from nse_recommender.db import get_connection, init_db


def test_init_db_creates_expected_tables():
    conn = get_connection(":memory:")
    init_db(conn)
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"bhavcopy_prices", "downloads_log", "recommendations"} <= tables


def test_get_connection_uses_row_factory():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute(
        "INSERT INTO downloads_log (date, status, message, fetched_at) VALUES (?,?,?,?)",
        ("2026-01-01", "success", "1 symbols", "2026-01-01T00:00:00"),
    )
    row = conn.execute("SELECT * FROM downloads_log").fetchone()
    assert row["date"] == "2026-01-01"
    assert isinstance(row, sqlite3.Row)


def test_init_db_is_idempotent():
    conn = get_connection(":memory:")
    init_db(conn)
    init_db(conn)  # must not raise
