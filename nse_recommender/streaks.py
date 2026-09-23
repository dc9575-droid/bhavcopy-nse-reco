def _sign(diff):
    if diff > 0:
        return 1
    if diff < 0:
        return -1
    return 0


def current_streak(conn, symbol):
    """How many consecutive trading days a symbol's close has moved in the
    same direction, and where that run began. Computed live from whatever
    bhavcopy_prices rows exist for this symbol, so it naturally extends (or
    resets) as more days of data are downloaded -- no separate update step.
    """
    rows = conn.execute(
        "SELECT date, close FROM bhavcopy_prices WHERE symbol = ? ORDER BY date ASC",
        (symbol,),
    ).fetchall()

    if not rows:
        return {
            "direction": None, "length": 0,
            "start_date": None, "start_price": None,
            "current_date": None, "current_price": None,
            "label": "—",
        }

    current_date, current_price = rows[-1]["date"], rows[-1]["close"]

    if len(rows) < 2:
        return {
            "direction": None, "length": 0,
            "start_date": current_date, "start_price": current_price,
            "current_date": current_date, "current_price": current_price,
            "label": "—",
        }

    diffs = [_sign(rows[i]["close"] - rows[i - 1]["close"]) for i in range(1, len(rows))]
    last_sign = diffs[-1]

    if last_sign == 0:
        return {
            "direction": None, "length": 0,
            "start_date": current_date, "start_price": current_price,
            "current_date": current_date, "current_price": current_price,
            "label": "—",
        }

    length = 0
    for d in reversed(diffs):
        if d != last_sign:
            break
        length += 1

    start_index = len(rows) - 1 - length
    start_date, start_price = rows[start_index]["date"], rows[start_index]["close"]
    direction = "up" if last_sign > 0 else "down"
    sign_char = "+" if last_sign > 0 else "-"

    return {
        "direction": direction,
        "length": length,
        "start_date": start_date,
        "start_price": start_price,
        "current_date": current_date,
        "current_price": current_price,
        "label": f"{sign_char}{length}d since {start_date}",
    }
