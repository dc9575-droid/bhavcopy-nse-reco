from nse_recommender import outcomes

_RESOLVED_STATUSES = ("target_hit", "stop_loss_hit")

HORIZON_ORDER = ["short_term", "mid_term", "long_term"]


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


def _tally_by_horizon_side(picks):
    buckets = {}
    for pick in picks:
        key = (pick["horizon"], pick["side"])
        counts = buckets.setdefault(key, {"target_hit": 0, "stop_loss_hit": 0})
        counts[pick["status"]] += 1
    rows = []
    for (horizon, side), counts in sorted(buckets.items()):
        total = counts["target_hit"] + counts["stop_loss_hit"]
        win_rate = round(100 * counts["target_hit"] / total) if total else None
        rows.append({
            "label": f"{horizon} / {side}",
            "horizon": horizon,
            "side": side,
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
        "by_horizon_side": _tally_by_horizon_side(picks),
        "by_streak_direction": _tally(picks, lambda p: p["streak_direction"]),
        "by_channel_position": _tally(picks, lambda p: outcomes.channel_bucket(p["channel_position_pct"])),
    }


def horizon_narratives(by_horizon_side):
    """One plain-language sentence per horizon comparing buy vs sell win
    rates -- e.g. "Of 63 resolved picks, SELL calls win 79% of the time
    vs 13% for BUY calls." A horizon with no resolved picks on either side
    is simply absent from the result; a horizon with only one side
    resolved gets a one-sided sentence instead of a comparison.
    """
    by_key = {(row["horizon"], row["side"]): row for row in by_horizon_side}
    narratives = {}
    for horizon in HORIZON_ORDER:
        buy = by_key.get((horizon, "buy"))
        sell = by_key.get((horizon, "sell"))
        if buy and sell:
            total = buy["total"] + sell["total"]
            if buy["win_rate"] > sell["win_rate"]:
                narratives[horizon] = (
                    f"Of {total} resolved picks, BUY calls win {buy['win_rate']}% of the time "
                    f"vs {sell['win_rate']}% for SELL calls."
                )
            elif sell["win_rate"] > buy["win_rate"]:
                narratives[horizon] = (
                    f"Of {total} resolved picks, SELL calls win {sell['win_rate']}% of the time "
                    f"vs {buy['win_rate']}% for BUY calls."
                )
            else:
                narratives[horizon] = (
                    f"Of {total} resolved picks, BUY and SELL calls have an equal "
                    f"{buy['win_rate']}% win rate so far."
                )
        elif buy:
            narratives[horizon] = (
                f"Only BUY calls have resolved so far ({buy['win_rate']}% win rate, {buy['total']} picks)."
            )
        elif sell:
            narratives[horizon] = (
                f"Only SELL calls have resolved so far ({sell['win_rate']}% win rate, {sell['total']} picks)."
            )
    return narratives
