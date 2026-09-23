from nse_recommender import calendar_nse

RANGE_LABELS = ["yesterday", "this_month", "last_month", "last_6_months"]


def coverage_summary(conn, today):
    row = conn.execute(
        "SELECT MIN(date) AS earliest, MAX(date) AS latest, COUNT(DISTINCT date) AS total "
        "FROM bhavcopy_prices"
    ).fetchone()
    ranges = {}
    for label in RANGE_LABELS:
        candidate_strs = [d.isoformat() for d in calendar_nse.range_for_label(label, today)]
        no_data = _count_no_data(conn, candidate_strs)
        ranges[label] = {
            "expected": len(candidate_strs) - no_data,
            "present": _count_present(conn, candidate_strs),
        }
    return {
        "earliest_date": row["earliest"],
        "latest_date": row["latest"],
        "total_days": row["total"] or 0,
        "ranges": ranges,
    }


def _count_no_data(conn, date_strs):
    if not date_strs:
        return 0
    placeholders = ",".join("?" * len(date_strs))
    row = conn.execute(
        f"SELECT COUNT(*) AS c FROM downloads_log WHERE status = 'no_data' AND date IN ({placeholders})",
        date_strs,
    ).fetchone()
    return row["c"]


def _count_present(conn, date_strs):
    if not date_strs:
        return 0
    placeholders = ",".join("?" * len(date_strs))
    row = conn.execute(
        f"SELECT COUNT(DISTINCT date) AS c FROM bhavcopy_prices WHERE date IN ({placeholders})",
        date_strs,
    ).fetchone()
    return row["c"]
