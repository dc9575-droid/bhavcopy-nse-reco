LOOKBACK_DAYS = 20
STD_MULTIPLIER = 2


def compute_channel(conn, symbol, lookback_days=LOOKBACK_DAYS):
    """Fits a straight line (least squares) through the trailing
    `lookback_days` closes and bands it at +/- STD_MULTIPLIER standard
    deviations of the residuals -- a simple support/resistance channel.
    Reports where the current price sits within that channel as a
    percentage (can go below 0% or above 100% if price has broken out).
    """
    rows = conn.execute(
        "SELECT date, close FROM bhavcopy_prices WHERE symbol = ? ORDER BY date ASC",
        (symbol,),
    ).fetchall()

    if len(rows) < lookback_days:
        return {"available": False, "have": len(rows), "need": lookback_days}

    window = rows[-lookback_days:]
    dates = [r["date"] for r in window]
    closes = [r["close"] for r in window]
    n = len(closes)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(closes) / n
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, closes))
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    slope = covariance / variance_x
    intercept = mean_y - slope * mean_x

    fitted = [intercept + slope * x for x in xs]
    residuals = [y - f for y, f in zip(closes, fitted)]
    resid_std = (sum(r ** 2 for r in residuals) / n) ** 0.5

    centerline_today = fitted[-1]
    upper = centerline_today + STD_MULTIPLIER * resid_std
    lower = centerline_today - STD_MULTIPLIER * resid_std
    current_price = closes[-1]

    width = upper - lower
    position_pct = 50.0 if width <= 0 else (current_price - lower) / width * 100

    support = round(lower, 2)
    resistance = round(upper, 2)

    # One-step-ahead linear extrapolation of this SAME fitted trend line --
    # not a prediction of where the price will actually go (nothing can
    # reliably do that), just where the existing line/band would sit if
    # extended by exactly one more day. The real close could land anywhere,
    # including outside this projected band, same as today's price can (and
    # does, on a breakout) sit outside the current support/resistance.
    next_centerline = intercept + slope * n

    return {
        "available": True,
        "lookback_days": lookback_days,
        "support": support,
        "resistance": resistance,
        "centerline": round(centerline_today, 2),
        "current_price": round(current_price, 2),
        "position_pct": round(position_pct, 1),
        "label": f"{round(position_pct)}% of {support}-{resistance}",
        "next_centerline": round(next_centerline, 2),
        "next_support": round(next_centerline - STD_MULTIPLIER * resid_std, 2),
        "next_resistance": round(next_centerline + STD_MULTIPLIER * resid_std, 2),
        "resid_std": resid_std,
        "points": [
            {"date": d, "close": c, "fitted": f}
            for d, c, f in zip(dates, closes, fitted)
        ],
    }
