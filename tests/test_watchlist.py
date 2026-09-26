from nse_recommender import watchlist
from nse_recommender.db import get_connection, init_db


def test_add_then_is_watched_returns_true():
    conn = get_connection(":memory:")
    init_db(conn)
    watchlist.add(conn, "RELIANCE")
    assert watchlist.is_watched(conn, "RELIANCE") is True


def test_is_watched_returns_false_for_a_symbol_never_added():
    conn = get_connection(":memory:")
    init_db(conn)
    assert watchlist.is_watched(conn, "RELIANCE") is False


def test_add_is_idempotent_on_repeat_calls():
    conn = get_connection(":memory:")
    init_db(conn)
    watchlist.add(conn, "RELIANCE")
    watchlist.add(conn, "RELIANCE")  # must not raise
    assert watchlist.list_watched(conn) == ["RELIANCE"]


def test_remove_makes_is_watched_return_false():
    conn = get_connection(":memory:")
    init_db(conn)
    watchlist.add(conn, "RELIANCE")
    watchlist.remove(conn, "RELIANCE")
    assert watchlist.is_watched(conn, "RELIANCE") is False


def test_remove_of_a_symbol_never_added_does_not_raise():
    conn = get_connection(":memory:")
    init_db(conn)
    watchlist.remove(conn, "RELIANCE")  # must not raise


def test_list_watched_returns_symbols_in_alphabetical_order():
    conn = get_connection(":memory:")
    init_db(conn)
    watchlist.add(conn, "TCS")
    watchlist.add(conn, "RELIANCE")
    watchlist.add(conn, "INFY")
    assert watchlist.list_watched(conn) == ["INFY", "RELIANCE", "TCS"]


def test_list_watched_is_empty_when_nothing_added():
    conn = get_connection(":memory:")
    init_db(conn)
    assert watchlist.list_watched(conn) == []
