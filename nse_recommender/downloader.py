import csv
import io
import zipfile
from datetime import datetime

import requests

BASE_URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.nseindia.com/",
}

REQUIRED_COLUMNS = [
    "TckrSymb", "SctySrs", "OpnPric", "HghPric", "LwPric", "ClsPric",
    "TtlTradgVol", "TradDt",
]


class NoDataForDate(Exception):
    """Raised when NSE has no bhavcopy for a date (holiday/weekend)."""


def build_url(d):
    return BASE_URL.format(date_str=d.strftime("%Y%m%d"))


def fetch_bhavcopy_csv(d, session=None):
    getter = session.get if session is not None else requests.get
    resp = getter(build_url(d), headers=HEADERS, timeout=30)
    if resp.status_code == 404:
        raise NoDataForDate(f"No bhavcopy published for {d.isoformat()}")
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        inner_name = zf.namelist()[0]
        return zf.read(inner_name).decode("utf-8")


def parse_bhavcopy_csv(csv_text, allowed_symbols):
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None or any(col not in reader.fieldnames for col in REQUIRED_COLUMNS):
        return []
    rows = []
    for r in reader:
        if r.get("SctySrs") != "EQ":
            continue
        symbol = r.get("TckrSymb")
        if symbol not in allowed_symbols:
            continue
        try:
            rows.append({
                "symbol": symbol,
                "date": r["TradDt"],
                "open": float(r["OpnPric"]),
                "high": float(r["HghPric"]),
                "low": float(r["LwPric"]),
                "close": float(r["ClsPric"]),
                "volume": int(float(r["TtlTradgVol"])),
            })
        except (ValueError, TypeError):
            continue
    return rows


def store_bhavcopy_rows(conn, rows):
    conn.executemany(
        """INSERT OR REPLACE INTO bhavcopy_prices (symbol, date, open, high, low, close, volume)
           VALUES (:symbol, :date, :open, :high, :low, :close, :volume)""",
        rows,
    )
    conn.commit()


def _log_download(conn, date_str, status, message):
    conn.execute(
        "INSERT OR REPLACE INTO downloads_log (date, status, message, fetched_at) VALUES (?, ?, ?, ?)",
        (date_str, status, message, datetime.utcnow().isoformat()),
    )
    conn.commit()


def download_missing_days(conn, dates, allowed_symbols, fetch_fn=None):
    fetch = fetch_fn if fetch_fn is not None else fetch_bhavcopy_csv
    results = {"success": [], "no_data": [], "failed": []}
    for d in dates:
        date_str = d.isoformat()
        existing = conn.execute(
            "SELECT status FROM downloads_log WHERE date = ?", (date_str,)
        ).fetchone()
        if existing is not None and existing["status"] in ("success", "no_data"):
            results[existing["status"]].append(date_str)
            continue
        try:
            csv_text = fetch(d)
        except NoDataForDate:
            _log_download(conn, date_str, "no_data", None)
            results["no_data"].append(date_str)
            continue
        except Exception as exc:
            _log_download(conn, date_str, "failed", str(exc))
            results["failed"].append(date_str)
            continue
        rows = parse_bhavcopy_csv(csv_text, allowed_symbols)
        store_bhavcopy_rows(conn, rows)
        _log_download(conn, date_str, "success", f"{len(rows)} symbols")
        results["success"].append(date_str)
    return results
