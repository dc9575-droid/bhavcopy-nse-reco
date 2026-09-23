from datetime import date

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


def test_download_route_redirects_to_index(client, monkeypatch):
    def always_no_data(d, session=None):
        raise downloader.NoDataForDate("no data for test")

    monkeypatch.setattr(downloader, "fetch_bhavcopy_csv", always_no_data)
    resp = client.post("/download/yesterday")
    assert resp.status_code in (302, 303)
