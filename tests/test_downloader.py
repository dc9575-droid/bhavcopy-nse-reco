import io
import zipfile
from datetime import date

import pytest

from nse_recommender import downloader
from nse_recommender.db import get_connection, init_db

SAMPLE_CSV = (
    "TradDt,ISIN,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,"
    "TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd\n"
    "2026-09-20,INE002A01018,RELIANCE,EQ,2500.00,2550.00,2490.00,2530.00,2528.00,2495.00,1234567,3000000000.00,45678\n"
    "2026-09-20,INE467B01029,TCS,EQ,3500.00,3550.00,3480.00,3520.00,3518.00,3510.00,234567,800000000.00,12345\n"
    "2026-09-20,INE999Z99999,SOMECO,BE,100.00,110.00,95.00,105.00,104.00,98.00,5000,500000.00,100\n"
)


def test_build_url_formats_date_as_yyyymmdd():
    url = downloader.build_url(date(2026, 9, 20))
    assert url == (
        "https://nsearchives.nseindia.com/content/cm/"
        "BhavCopy_NSE_CM_0_0_0_20260920_F_0000.csv.zip"
    )


def test_parse_bhavcopy_csv_keeps_only_eq_series_and_allowed_symbols():
    rows = downloader.parse_bhavcopy_csv(SAMPLE_CSV, allowed_symbols={"RELIANCE", "TCS"})
    assert [r["symbol"] for r in rows] == ["RELIANCE", "TCS"]


def test_parse_bhavcopy_csv_maps_ohlcv_fields():
    rows = downloader.parse_bhavcopy_csv(SAMPLE_CSV, allowed_symbols={"RELIANCE"})
    reliance = rows[0]
    assert reliance["date"] == "2026-09-20"
    assert reliance["open"] == 2500.00
    assert reliance["high"] == 2550.00
    assert reliance["low"] == 2490.00
    assert reliance["close"] == 2530.00
    assert reliance["volume"] == 1234567


def test_parse_bhavcopy_csv_skips_malformed_row():
    bad_csv = SAMPLE_CSV.replace(
        "2500.00,2550.00,2490.00,2530.00", "N/A,2550.00,2490.00,2530.00"
    )
    rows = downloader.parse_bhavcopy_csv(bad_csv, allowed_symbols={"RELIANCE", "TCS"})
    assert [r["symbol"] for r in rows] == ["TCS"]


def test_parse_bhavcopy_csv_returns_empty_when_required_column_missing():
    header_only = (
        "TradDt,ISIN,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,LastPric,PrvsClsgPric,"
        "TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd\n"
    )
    rows = downloader.parse_bhavcopy_csv(header_only, allowed_symbols={"RELIANCE"})
    assert rows == []


class FakeResponse:
    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code != 404:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, response):
        self._response = response

    def get(self, url, headers=None, timeout=None):
        return self._response


def _zip_bytes(csv_text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bhav.csv", csv_text)
    return buf.getvalue()


def test_fetch_bhavcopy_csv_returns_decoded_csv_on_success():
    session = FakeSession(FakeResponse(200, _zip_bytes(SAMPLE_CSV)))
    text = downloader.fetch_bhavcopy_csv(date(2026, 9, 20), session=session)
    assert "RELIANCE" in text


def test_fetch_bhavcopy_csv_raises_no_data_on_404():
    session = FakeSession(FakeResponse(404))
    with pytest.raises(downloader.NoDataForDate):
        downloader.fetch_bhavcopy_csv(date(2026, 9, 20), session=session)


def test_store_bhavcopy_rows_is_idempotent():
    conn = get_connection(":memory:")
    init_db(conn)
    rows = downloader.parse_bhavcopy_csv(SAMPLE_CSV, allowed_symbols={"RELIANCE", "TCS"})
    downloader.store_bhavcopy_rows(conn, rows)
    downloader.store_bhavcopy_rows(conn, rows)
    count = conn.execute("SELECT COUNT(*) AS c FROM bhavcopy_prices").fetchone()["c"]
    assert count == 2
