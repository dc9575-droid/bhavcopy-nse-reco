import pandas as pd

from nse_recommender import chart, channel, news, streaks

HORIZONS = {
    "short_term": {"label": "Short-term (3 trading days)", "lookback_days": 3, "target_pct": 0.05, "stop_loss_pct": 0.025},
    "mid_term": {"label": "Mid-term (~2 weeks)", "lookback_days": 10, "target_pct": 0.10, "stop_loss_pct": 0.05},
    "long_term": {"label": "Long-term (~2 months)", "lookback_days": 40, "target_pct": 0.20, "stop_loss_pct": 0.10},
}


class InsufficientData(Exception):
    def __init__(self, have, need):
        self.have = have
        self.need = need
        super().__init__(f"Have {have} trading days of data, need {need}")


def compute_returns(conn, symbols, lookback_days):
    if not symbols:
        raise InsufficientData(have=0, need=lookback_days + 1)
    placeholders = ",".join("?" * len(symbols))
    df = pd.read_sql_query(
        f"SELECT symbol, date, close FROM bhavcopy_prices WHERE symbol IN ({placeholders}) ORDER BY date",
        conn,
        params=symbols,
    )
    all_dates = sorted(df["date"].unique())
    if len(all_dates) < lookback_days + 1:
        raise InsufficientData(have=len(all_dates), need=lookback_days + 1)
    latest_date = all_dates[-1]
    base_date = all_dates[-(lookback_days + 1)]
    latest = df[df["date"] == latest_date].set_index("symbol")["close"]
    base = df[df["date"] == base_date].set_index("symbol")["close"]
    joined = latest.to_frame("entry").join(base.to_frame("base"), how="inner")
    joined["pct_return"] = (joined["entry"] - joined["base"]) / joined["base"]
    joined["entry_date"] = latest_date
    return joined.reset_index().sort_values("pct_return", ascending=False).reset_index(drop=True)


def _levels(entry, side, target_pct, stop_loss_pct, mood_score=0.0):
    alignment = mood_score if side == "buy" else -mood_score
    adjusted_stop_loss_pct = stop_loss_pct * (1 + news.MOOD_ADJUSTMENT * alignment)
    if side == "buy":
        return entry * (1 + target_pct), entry * (1 - adjusted_stop_loss_pct)
    return entry * (1 - target_pct), entry * (1 + adjusted_stop_loss_pct)


def _build_picks(conn, rows, side, config, mood_score=0.0):
    picks = []
    for _, row in rows.iterrows():
        target, stop_loss = _levels(
            row["entry"], side, config["target_pct"], config["stop_loss_pct"], mood_score
        )
        pct = row["pct_return"] * 100
        picks.append({
            "symbol": row["symbol"],
            "entry": round(row["entry"], 2),
            "entry_date": row["entry_date"],
            "target": round(target, 2),
            "stop_loss": round(stop_loss, 2),
            "reason": f"{pct:+.1f}% over last {config['lookback_days']} trading days",
            "streak": streaks.current_streak(conn, row["symbol"]),
            "channel": channel.compute_channel(conn, row["symbol"]),
        })
    for pick in picks:
        pick["chart_svg"] = chart.channel_svg(pick["channel"])
        pick["next_chart_svg"] = chart.next_day_projection_svg(pick["channel"])
    return picks


def generate_recommendations(conn, symbols, horizon_key, mood_score=0.0):
    config = HORIZONS[horizon_key]
    try:
        ranked = compute_returns(conn, symbols, config["lookback_days"])
    except InsufficientData as exc:
        return {"status": "insufficient_data", "have": exc.have, "need": exc.need, "label": config["label"]}
    top5 = ranked.head(5)
    bottom5 = ranked.tail(5).iloc[::-1]
    return {
        "status": "ok",
        "label": config["label"],
        "buy": _build_picks(conn, top5, "buy", config, mood_score),
        "sell": _build_picks(conn, bottom5, "sell", config, mood_score),
    }


def save_recommendations(conn, horizon_key, generated_date, result):
    if result["status"] != "ok":
        return
    for side in ("buy", "sell"):
        for pick in result[side]:
            conn.execute(
                """INSERT OR IGNORE INTO recommendations
                   (symbol, horizon, side, generated_date, entry_date, entry, target, stop_loss)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    pick["symbol"], horizon_key, side, generated_date, pick["entry_date"],
                    pick["entry"], pick["target"], pick["stop_loss"],
                ),
            )
    conn.commit()


def symbol_momentum(conn, symbol, horizon_key):
    """Same return/reason math as a recommendation pick, but for one
    arbitrary symbol regardless of whether it was ranked into the top/bottom
    5 -- used by stock search, which shows info without implying a specific
    buy/sell call."""
    config = HORIZONS[horizon_key]
    try:
        df = compute_returns(conn, [symbol], config["lookback_days"])
    except InsufficientData as exc:
        return {"status": "insufficient_data", "have": exc.have, "need": exc.need, "label": config["label"]}
    if df.empty:
        return {
            "status": "insufficient_data",
            "have": 0,
            "need": config["lookback_days"] + 1,
            "label": config["label"],
        }
    row = df.iloc[0]
    pct = row["pct_return"] * 100
    return {
        "status": "ok",
        "label": config["label"],
        "entry": round(row["entry"], 2),
        "entry_date": row["entry_date"],
        "reason": f"{pct:+.1f}% over last {config['lookback_days']} trading days",
    }


def generate_and_save_all(conn, symbols, generated_date):
    results = {}
    for horizon_key in HORIZONS:
        result = generate_recommendations(conn, symbols, horizon_key)
        save_recommendations(conn, horizon_key, generated_date, result)
        results[horizon_key] = result
    return results
