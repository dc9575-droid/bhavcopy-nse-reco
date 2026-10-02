from nse_recommender import outcomes

_RESOLVED_STATUSES = ("target_hit", "stop_loss_hit")


def _channel_bucket(pct):
    if pct is None:
        return None
    if pct < 80:
        return "Below support (<80%)"
    if pct <= 100:
        return "Within channel (80-100%)"
    return "Broken above (>100%)"


def _tally(picks, key_fn):
    buckets = {}
    for pick in picks:
        key = key_fn(pick)
        if key is None:
            continue
        counts = buckets.setdefault(key, {"target_hit": 0, "stop_loss_hit": 0})
        counts[pick["status"]] += 1
    rows = []
    for label, counts in sorted(buckets.items()):
        total = counts["target_hit"] + counts["stop_loss_hit"]
        win_rate = round(100 * counts["target_hit"] / total) if total else None
        rows.append({
            "label": label,
            "target_hit": counts["target_hit"],
            "stop_loss_hit": counts["stop_loss_hit"],
            "total": total,
            "win_rate": win_rate,
        })
    return rows


def win_rate_by_segment(conn):
    """Breaks down resolved past picks (target_hit/stop_loss_hit only --
    still_open picks haven't resolved yet, so they carry no win/loss signal)
    by horizon+side, streak direction at entry, and channel position at
    entry. The entry-condition columns are nullable -- they're only
    populated for picks generated after that tracking began, so those two
    breakdowns start empty and fill in as new recommendations accumulate.
    """
    picks = [p for p in outcomes.list_past_picks(conn) if p["status"] in _RESOLVED_STATUSES]
    return {
        "by_horizon_side": _tally(picks, lambda p: f"{p['horizon']} / {p['side']}"),
        "by_streak_direction": _tally(picks, lambda p: p["streak_direction"]),
        "by_channel_position": _tally(picks, lambda p: _channel_bucket(p["channel_position_pct"])),
    }
