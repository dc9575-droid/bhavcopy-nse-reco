from datetime import date, timedelta

# Reporting cadence per horizon (how results get grouped for review), not an
# expiry: a pick only ever resolves when its price actually hits target or
# stop-loss, however long that takes. Long-term buckets are always exactly
# two mid-term weeks (both anchored to Monday), so a pick's mid-term week and
# long-term bucket agree whenever they overlap.
_LONG_TERM_BUCKET_ANCHOR = date(2000, 1, 3)  # a Monday


def period_start(horizon_key, generated_date):
    if horizon_key == "short_term":
        return generated_date
    if horizon_key == "mid_term":
        return generated_date - timedelta(days=generated_date.weekday())
    if horizon_key == "long_term":
        days_since_anchor = (generated_date - _LONG_TERM_BUCKET_ANCHOR).days
        bucket_index = days_since_anchor // 14
        return _LONG_TERM_BUCKET_ANCHOR + timedelta(days=bucket_index * 14)
    raise ValueError(f"Unknown horizon: {horizon_key}")


def _period_label(horizon_key, p_start):
    if horizon_key == "short_term":
        return p_start.isoformat()
    if horizon_key == "mid_term":
        return f"Week of {p_start.isoformat()}"
    period_end = p_start + timedelta(days=13)
    return f"{p_start.isoformat()} to {period_end.isoformat()}"


def daily_results(conn):
    buckets = {}
    for pick in list_past_picks(conn):
        horizon = pick["horizon"]
        generated_date = date.fromisoformat(pick["generated_date"])
        p_start = period_start(horizon, generated_date)
        key = (horizon, p_start)
        counts = buckets.setdefault(key, {"target_hit": 0, "stop_loss_hit": 0, "still_open": 0})
        counts[pick["status"]] += 1

    results = {"short_term": [], "mid_term": [], "long_term": []}
    for (horizon, p_start), counts in buckets.items():
        resolved = counts["target_hit"] + counts["stop_loss_hit"]
        win_rate = round(100 * counts["target_hit"] / resolved) if resolved else None
        results[horizon].append({
            "period_start": p_start.isoformat(),
            "period_label": _period_label(horizon, p_start),
            "target_hit": counts["target_hit"],
            "stop_loss_hit": counts["stop_loss_hit"],
            "still_open": counts["still_open"],
            "total": resolved + counts["still_open"],
            "win_rate": win_rate,
        })
    for horizon in results:
        results[horizon].sort(key=lambda row: row["period_start"], reverse=True)
    return results


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


def filter_picks(picks, horizon=None, period=None, status=None):
    """Narrow an already-computed list_past_picks() result to the picks
    behind one Daily Results cell -- e.g. clicking a "Stop-Loss Hit" count
    for a given horizon/period should show exactly those picks.
    """
    result = picks
    if horizon:
        result = [p for p in result if p["horizon"] == horizon]
    if period:
        result = [
            p for p in result
            if period_start(p["horizon"], date.fromisoformat(p["generated_date"])).isoformat() == period
        ]
    if status:
        result = [p for p in result if p["status"] == status]
    return result
