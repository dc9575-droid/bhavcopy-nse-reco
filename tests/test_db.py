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


def test_recommendations_table_has_entry_condition_columns():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute(
        """INSERT INTO recommendations
           (symbol, horizon, side, generated_date, entry_date, entry, target, stop_loss,
            streak_direction, streak_length, channel_position_pct)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        ("RELIANCE", "short_term", "buy", "2026-01-01", "2026-01-01", 100, 105, 97.5, "up", 5, 92.3),
    )
    row = conn.execute("SELECT * FROM recommendations WHERE symbol='RELIANCE'").fetchone()
    assert row["streak_direction"] == "up"
    assert row["streak_length"] == 5
    assert row["channel_position_pct"] == 92.3


def test_init_db_adds_entry_condition_columns_to_a_pre_existing_table_without_raising():
    # Simulates a real deployed DB created before this migration: a bare
    # recommendations table with none of the new columns yet.
    conn = get_connection(":memory:")
    conn.execute("""CREATE TABLE recommendations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        horizon TEXT NOT NULL,
        side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
        generated_date TEXT NOT NULL,
        entry_date TEXT NOT NULL,
        entry REAL NOT NULL,
        target REAL NOT NULL,
        stop_loss REAL NOT NULL,
        UNIQUE (symbol, horizon, side, generated_date)
    )""")
    conn.commit()
    init_db(conn)  # must not raise, and must add the new columns
    init_db(conn)  # calling twice must also not raise (idempotent migration)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(recommendations)").fetchall()}
    assert {"streak_direction", "streak_length", "channel_position_pct"} <= columns
