from datetime import date, timedelta

from nse_recommender import streaks
from nse_recommender.db import get_connection, init_db


def _insert_price(conn, symbol, d, close):
    conn.execute(
        "INSERT INTO bhavcopy_prices (symbol, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
        (symbol, d.isoformat(), close, close, close, close, 1000),
    )
    conn.commit()


def _seed(conn, symbol, closes, start=date(2026, 9, 15)):
    for i, close in enumerate(closes):
        _insert_price(conn, symbol, start + timedelta(days=i), close)


def test_current_streak_detects_up_streak_and_its_start():
    conn = get_connection(":memory:")
    init_db(conn)
    # 100 -> 105 (up) -> 110 (up) -> 115 (up): a 3-day up streak starting
    # from the 100 baseline on the first date.
    _seed(conn, "AAA", [100, 105, 110, 115])
    result = streaks.current_streak(conn, "AAA")
    assert result["direction"] == "up"
    assert result["length"] == 3
    assert result["start_date"] == "2026-09-15"
    assert result["start_price"] == 100
    assert result["current_date"] == "2026-09-18"
    assert result["current_price"] == 115
    assert result["label"] == "+3d since 2026-09-15"


def test_current_streak_detects_down_streak():
    conn = get_connection(":memory:")
    init_db(conn)
    _seed(conn, "BBB", [200, 190, 180])
    result = streaks.current_streak(conn, "BBB")
    assert result["direction"] == "down"
    assert result["length"] == 2
    assert result["start_date"] == "2026-09-15"
    assert result["start_price"] == 200
    assert result["label"] == "-2d since 2026-09-15"


def test_current_streak_stops_at_the_direction_change():
    conn = get_connection(":memory:")
    init_db(conn)
    # down, down, then up, up, up (most recent run): streak should only
    # count the trailing up-run, starting right after the last down day.
    _seed(conn, "CCC", [150, 140, 130, 135, 140, 145])
    result = streaks.current_streak(conn, "CCC")
    assert result["direction"] == "up"
    assert result["length"] == 3
    assert result["start_date"] == "2026-09-17"  # the 130 baseline day
    assert result["start_price"] == 130


def test_current_streak_flat_day_breaks_the_streak():
    conn = get_connection(":memory:")
    init_db(conn)
    _seed(conn, "DDD", [100, 105, 105])
    result = streaks.current_streak(conn, "DDD")
    assert result["direction"] is None
    assert result["length"] == 0
    assert result["label"] == "—"


def test_current_streak_single_days_move_has_length_one():
    conn = get_connection(":memory:")
    init_db(conn)
    _seed(conn, "EEE", [100, 110])
    result = streaks.current_streak(conn, "EEE")
    assert result["direction"] == "up"
    assert result["length"] == 1
    assert result["start_date"] == "2026-09-15"


def test_current_streak_with_fewer_than_two_days_is_none():
    conn = get_connection(":memory:")
    init_db(conn)
    _seed(conn, "FFF", [100])
    result = streaks.current_streak(conn, "FFF")
    assert result["direction"] is None
    assert result["length"] == 0
    assert result["label"] == "—"


def test_current_streak_with_no_data_at_all_is_none():
    conn = get_connection(":memory:")
    init_db(conn)
    result = streaks.current_streak(conn, "GGG")
    assert result["direction"] is None
    assert result["length"] == 0
    assert result["current_date"] is None


def test_current_streak_extends_when_a_new_matching_day_is_added():
    # This is the "continues tomorrow" behavior: the function is computed
    # live from stored rows, so adding one more up-day extends the streak
    # by exactly one with no other change needed.
    conn = get_connection(":memory:")
    init_db(conn)
    _seed(conn, "HHH", [100, 105, 110])
    before = streaks.current_streak(conn, "HHH")
    assert before["length"] == 2
    _insert_price(conn, "HHH", date(2026, 9, 18), 115)  # "tomorrow"
    after = streaks.current_streak(conn, "HHH")
    assert after["length"] == 3
    assert after["current_date"] == "2026-09-18"
    assert after["current_price"] == 115
