from datetime import date, timedelta

import pytest

from app import create_app
from nse_recommender import downloader

SYMBOLS = ["RELIANCE", "TCS"]
HEADER = (
    "TradDt,ISIN,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,"
    "TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd"
)
TEST_DATES = [date(2026, 9, 14 + i) for i in range(5)]


def _csv_for(d, reliance_close, tcs_close):
    return "\n".join([
        HEADER,
        f"{d.isoformat()},INE002A01018,RELIANCE,EQ,{reliance_close},{reliance_close},{reliance_close},"
        f"{reliance_close},{reliance_close},{reliance_close},100000,1.0,10",
        f"{d.isoformat()},INE467B01029,TCS,EQ,{tcs_close},{tcs_close},{tcs_close},"
        f"{tcs_close},{tcs_close},{tcs_close},100000,1.0,10",
    ])


@pytest.fixture
def client(tmp_path):
    # Must be a real file, not ":memory:" — an in-memory SQLite DB is private
    # to a single connection, and each request in this app opens its own.
    db_path = tmp_path / "test_nse.db"

    def fake_fetch(d, session=None):
        idx = TEST_DATES.index(d)
        return _csv_for(d, 100 + idx, 200 - idx)

    app = create_app(db_path=str(db_path), symbols=SYMBOLS)

    from nse_recommender.db import get_connection
    conn = get_connection(str(db_path))
    downloader.download_missing_days(conn, TEST_DATES, set(SYMBOLS), fetch_fn=fake_fetch)
    conn.close()

    return app.test_client()


def test_index_page_shows_coverage(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Coverage" in resp.data


def test_recommendations_page_shows_short_term_and_flags_insufficient_long_term(client):
    resp = client.get("/recommendations")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Short-term" in body
    assert "RELIANCE" in body
    assert "download more history" in body  # long_term needs 41 days, only have 5


def test_past_picks_page_lists_generated_recommendations(client):
    client.get("/recommendations")
    resp = client.get("/past-picks")
    assert resp.status_code == 200
    assert b"RELIANCE" in resp.data


def test_past_picks_daily_results_counts_link_to_filtered_all_picks(client):
    client.get("/recommendations")
    resp = client.get("/past-picks")
    body = resp.data.decode()
    # entry_date is the fixture's last seeded day, so nothing has any later
    # price to resolve against yet -- every pick is still_open, giving the
    # Daily Results table a clickable "Still Open" count to link from.
    assert "horizon=short_term" in body
    assert "status=still_open" in body


def test_past_picks_page_filters_by_status_query_param(client):
    client.get("/recommendations")
    resp = client.get("/past-picks?horizon=short_term&status=still_open")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Showing" in body
    assert "Clear filter" in body
    # Every short-term pick is still_open in this fixture (see above), so
    # both symbols should appear in the filtered list.
    assert "RELIANCE" in body
    assert "TCS" in body


def test_past_picks_page_shows_no_filter_banner_without_query_params(client):
    client.get("/recommendations")
    resp = client.get("/past-picks")
    assert b"Clear filter" not in resp.data


def test_download_route_redirects_to_index(client, monkeypatch):
    def always_no_data(d, session=None):
        raise downloader.NoDataForDate("no data for test")

    monkeypatch.setattr(downloader, "fetch_bhavcopy_csv", always_no_data)
    resp = client.post("/download/yesterday")
    assert resp.status_code in (302, 303)


def test_stock_search_with_no_symbol_shows_a_prompt(client):
    resp = client.get("/stock")
    assert resp.status_code == 200
    assert b"Search for a symbol" in resp.data


def test_stock_search_shows_streak_and_momentum_for_a_known_symbol(client):
    resp = client.get("/stock?symbol=reliance")  # lowercase, must be normalized
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "RELIANCE" in body
    assert "+4d since" in body  # RELIANCE's close rises every day in the fixture
    # Only 5 days of history are seeded, far short of the channel's 20-day
    # requirement, so it must degrade gracefully rather than error.
    assert "Need 20" in body or "need" in body.lower()


def test_stock_search_for_symbol_outside_the_universe_shows_a_message(client):
    resp = client.get("/stock?symbol=NOTINUNIVERSE")
    assert resp.status_code == 200
    assert b"not in the bundled Nifty 500 list" in resp.data


def test_watchlist_page_is_empty_by_default(client):
    resp = client.get("/watchlist")
    assert resp.status_code == 200
    assert b"Nothing watched yet" in resp.data


def test_stock_page_shows_add_to_watchlist_button_for_an_unwatched_symbol(client):
    resp = client.get("/stock?symbol=reliance")
    assert resp.status_code == 200
    assert b"Add to Watchlist" in resp.data


def test_adding_to_watchlist_makes_it_appear_on_the_watchlist_page(client):
    client.post("/watchlist/add", data={"symbol": "reliance"}, follow_redirects=True)
    resp = client.get("/watchlist")
    body = resp.data.decode()
    assert "RELIANCE" in body
    assert "Nothing watched yet" not in body


def test_adding_to_watchlist_redirects_back_to_the_stock_page_and_shows_remove_button(client):
    resp = client.post(
        "/watchlist/add",
        data={"symbol": "RELIANCE", "next": "/stock?symbol=RELIANCE"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Remove from Watchlist" in resp.data


def test_removing_from_watchlist_takes_it_off_the_watchlist_page(client):
    client.post("/watchlist/add", data={"symbol": "RELIANCE"})
    client.post("/watchlist/remove", data={"symbol": "RELIANCE"})
    resp = client.get("/watchlist")
    assert b"Nothing watched yet" in resp.data


def test_watchlist_add_ignores_a_symbol_outside_the_universe(client):
    client.post("/watchlist/add", data={"symbol": "NOTINUNIVERSE"})
    resp = client.get("/watchlist")
    assert b"Nothing watched yet" in resp.data


def test_download_route_flashes_summary_message(client, monkeypatch):
    from nse_recommender import calendar_nse

    # Force a deterministic single candidate date regardless of what day the
    # test happens to run on (weekends would otherwise make "yesterday"
    # resolve to an empty list).
    monkeypatch.setattr(calendar_nse, "range_for_label", lambda label, today: [date(2026, 1, 5)])

    def always_no_data(d, session=None):
        raise downloader.NoDataForDate("no data for test")

    monkeypatch.setattr(downloader, "fetch_bhavcopy_csv", always_no_data)
    resp = client.post("/download/yesterday", follow_redirects=True)
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "0 downloaded, 1 no data, 0 failed" in body


@pytest.fixture
def client_with_channel_data(tmp_path):
    # The plain `client` fixture only seeds 5 days of history, far short of
    # the channel's 20-day requirement, so its channel drawer (and the
    # watchlist button living inside it) never renders. This fixture seeds
    # enough history for the channel to actually be available.
    db_path = tmp_path / "test_nse_channel.db"
    symbols = ["RELIANCE"]
    app = create_app(db_path=str(db_path), symbols=symbols)

    from nse_recommender.db import get_connection
    conn = get_connection(str(db_path))
    base = date(2026, 8, 1)
    for i in range(25):
        d = base + timedelta(days=i)
        close = 100 + i
        conn.execute(
            "INSERT INTO bhavcopy_prices (symbol, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
            ("RELIANCE", d.isoformat(), close, close, close, close, 1000),
        )
    conn.commit()
    conn.close()
    return app.test_client()


def test_recommendations_page_shows_add_to_watchlist_in_the_channel_drawer(client_with_channel_data):
    resp = client_with_channel_data.get("/recommendations")
    assert b"Add to Watchlist" in resp.data


def test_recommendations_page_shows_remove_for_an_already_watched_symbol(client_with_channel_data):
    client_with_channel_data.post("/watchlist/add", data={"symbol": "RELIANCE"})
    resp = client_with_channel_data.get("/recommendations")
    assert b"Remove from Watchlist" in resp.data


def test_recommendations_page_shows_market_mood_banner(client):
    resp = client.get("/recommendations")
    body = resp.data.decode()
    assert "Market Mood" in body
    # No feeds are reachable in tests (conftest.py blocks real network and
    # no market_mood row was pre-seeded), so this must show the neutral
    # degraded state, not crash or silently omit the banner.
    assert "Unavailable" in body
