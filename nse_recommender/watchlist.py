def add(conn, symbol):
    conn.execute("INSERT OR IGNORE INTO watchlist (symbol) VALUES (?)", (symbol,))
    conn.commit()


def remove(conn, symbol):
    conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))
    conn.commit()


def is_watched(conn, symbol):
    row = conn.execute("SELECT 1 FROM watchlist WHERE symbol = ?", (symbol,)).fetchone()
    return row is not None


def list_watched(conn):
    rows = conn.execute("SELECT symbol FROM watchlist ORDER BY symbol ASC").fetchall()
    return [row["symbol"] for row in rows]
