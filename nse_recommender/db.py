import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "nse.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS bhavcopy_prices (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS downloads_log (
    date TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    message TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendations (
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
);

CREATE TABLE IF NOT EXISTS market_mood (
    date TEXT PRIMARY KEY,
    score REAL NOT NULL,
    label TEXT NOT NULL,
    headlines_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    symbol TEXT PRIMARY KEY
);
"""


def get_connection(db_path=None):
    conn = sqlite3.connect(str(db_path) if db_path is not None else str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# SQLite has no "ALTER TABLE ... ADD COLUMN IF NOT EXISTS", so adding a
# column to a table that may already exist (and already have real rows, on
# a live deployment) has to check first -- otherwise a second init_db() call
# raises "duplicate column name".
_RECOMMENDATIONS_COLUMNS = {
    "streak_direction": "TEXT",
    "streak_length": "INTEGER",
    "channel_position_pct": "REAL",
}


def _ensure_columns(conn, table, columns):
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, coltype in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {coltype}")


def init_db(conn):
    conn.executescript(SCHEMA)
    _ensure_columns(conn, "recommendations", _RECOMMENDATIONS_COLUMNS)
    conn.commit()
