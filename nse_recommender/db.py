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
    side TEXT NOT NULL,
    generated_date TEXT NOT NULL,
    entry REAL NOT NULL,
    target REAL NOT NULL,
    stop_loss REAL NOT NULL
);
"""


def get_connection(db_path=None):
    conn = sqlite3.connect(str(db_path) if db_path is not None else str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    conn.executescript(SCHEMA)
    conn.commit()
