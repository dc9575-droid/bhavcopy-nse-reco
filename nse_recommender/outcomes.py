def compute_outcome(conn, rec):
    cur = conn.execute(
        "SELECT date, close FROM bhavcopy_prices WHERE symbol = ? AND date > ? ORDER BY date ASC",
        (rec["symbol"], rec["entry_date"]),
    )
    later_prices = cur.fetchall()
    for row in later_prices:
        close = row["close"]
        if rec["side"] == "buy":
            if close >= rec["target"]:
                return {"status": "target_hit", "as_of_date": row["date"], "current_price": close}
            if close <= rec["stop_loss"]:
                return {"status": "stop_loss_hit", "as_of_date": row["date"], "current_price": close}
        else:
            if close <= rec["target"]:
                return {"status": "target_hit", "as_of_date": row["date"], "current_price": close}
            if close >= rec["stop_loss"]:
                return {"status": "stop_loss_hit", "as_of_date": row["date"], "current_price": close}
    if later_prices:
        last = later_prices[-1]
        return {"status": "still_open", "as_of_date": last["date"], "current_price": last["close"]}
    return {"status": "still_open", "as_of_date": rec["entry_date"], "current_price": rec["entry"]}


def list_past_picks(conn):
    rows = conn.execute(
        "SELECT * FROM recommendations ORDER BY generated_date DESC, id DESC"
    ).fetchall()
    picks = []
    for row in rows:
        rec = dict(row)
        outcome = compute_outcome(conn, rec)
        picks.append({**rec, **outcome})
    return picks
