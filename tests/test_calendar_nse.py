from datetime import date, timedelta

import pytest

from nse_recommender import calendar_nse


def test_candidate_days_excludes_weekends():
    days = calendar_nse.candidate_days(date(2024, 1, 1), date(2024, 1, 7))
    assert days == [
        date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3),
        date(2024, 1, 4), date(2024, 1, 5),
    ]


def test_candidate_days_single_weekday():
    assert calendar_nse.candidate_days(date(2024, 1, 3), date(2024, 1, 3)) == [date(2024, 1, 3)]


def test_candidate_days_single_weekend_day_is_empty():
    assert calendar_nse.candidate_days(date(2024, 1, 6), date(2024, 1, 6)) == []


def test_range_for_label_yesterday_on_a_weekend_is_empty():
    today = date(2024, 1, 15)  # Monday; yesterday = Sunday Jan 14
    assert calendar_nse.range_for_label("yesterday", today) == []


def test_range_for_label_yesterday_on_a_weekday():
    today = date(2024, 1, 16)  # Tuesday; yesterday = Monday Jan 15
    assert calendar_nse.range_for_label("yesterday", today) == [date(2024, 1, 15)]


def test_range_for_label_this_month_uses_month_boundaries():
    today = date(2024, 1, 15)
    expected = calendar_nse.candidate_days(date(2024, 1, 1), date(2024, 1, 15))
    assert calendar_nse.range_for_label("this_month", today) == expected


def test_range_for_label_last_month_uses_previous_calendar_month():
    today = date(2024, 1, 15)
    expected = calendar_nse.candidate_days(date(2023, 12, 1), date(2023, 12, 31))
    assert calendar_nse.range_for_label("last_month", today) == expected


def test_range_for_label_last_6_months_spans_approximately_182_days_back():
    today = date(2024, 1, 15)
    expected = calendar_nse.candidate_days(today - timedelta(days=182), today)
    assert calendar_nse.range_for_label("last_6_months", today) == expected


def test_range_for_label_unknown_label_raises():
    with pytest.raises(ValueError):
        calendar_nse.range_for_label("bogus", date(2024, 1, 15))
