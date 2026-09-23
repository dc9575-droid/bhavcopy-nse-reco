from datetime import date, timedelta


def candidate_days(start, end):
    """Weekdays (Mon-Fri) between start and end inclusive. NSE holidays among
    these are discovered at download time (404 response), not predicted here."""
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def range_for_label(label, today):
    if label == "yesterday":
        d = today - timedelta(days=1)
        return candidate_days(d, d)
    if label == "this_month":
        # Exclude today: NSE may not have published today's bhavcopy yet
        # (it typically appears around 18:00 IST), and a 404 for "today" would
        # otherwise be misfiled as a genuine no_data/holiday rather than
        # "not yet published". Today's data is only ever fetched via a later
        # day's "yesterday" click, once it's safe to trust a 404 as a holiday.
        return candidate_days(today.replace(day=1), today - timedelta(days=1))
    if label == "last_month":
        first_this_month = today.replace(day=1)
        last_month_end = first_this_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return candidate_days(last_month_start, last_month_end)
    if label == "last_6_months":
        return candidate_days(today - timedelta(days=182), today - timedelta(days=1))
    raise ValueError(f"Unknown range label: {label}")
