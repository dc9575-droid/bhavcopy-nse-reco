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
        return candidate_days(today.replace(day=1), today)
    if label == "last_month":
        first_this_month = today.replace(day=1)
        last_month_end = first_this_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return candidate_days(last_month_start, last_month_end)
    if label == "last_6_months":
        return candidate_days(today - timedelta(days=182), today)
    raise ValueError(f"Unknown range label: {label}")
