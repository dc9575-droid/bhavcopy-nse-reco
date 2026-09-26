import sqlite3

import pytest

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


def test_init_db_creates_market_mood_table():
    conn = get_connection(":memory:")
    init_db(conn)
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "market_mood" in tables


def test_market_mood_table_columns():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute(
        "INSERT INTO market_mood (date, score, label, headlines_json, fetched_at) VALUES (?,?,?,?,?)",
        ("2026-01-01", 0.5, "Bullish", "[]", "2026-01-01T00:00:00"),
    )
    row = conn.execute("SELECT * FROM market_mood WHERE date = ?", ("2026-01-01",)).fetchone()
    assert row["score"] == 0.5
    assert row["label"] == "Bullish"
    assert row["headlines_json"] == "[]"


def test_init_db_creates_watchlist_table():
    conn = get_connection(":memory:")
    init_db(conn)
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "watchlist" in tables


def test_watchlist_symbol_is_the_primary_key():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute("INSERT INTO watchlist (symbol) VALUES (?)", ("RELIANCE",))
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO watchlist (symbol) VALUES (?)", ("RELIANCE",))
