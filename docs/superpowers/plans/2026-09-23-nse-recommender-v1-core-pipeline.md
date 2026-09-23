# NSE Recommender V1 Core Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Flask + SQLite app that downloads NSE EOD bhavcopy data for chosen date ranges, ranks Nifty 500 stocks into short/mid/long-term buy & sell picks, and tracks whether past picks hit their target or stop-loss.

**Architecture:** A single Python process. Flask serves three server-rendered pages (downloader/status, recommendations, past picks). SQLite (`nse.db`, file-based) stores bhavcopy prices, download attempt history, and generated recommendations. pandas does the return-ranking math. No background workers — every action runs synchronously on request.

**Tech Stack:** Python 3.10+, Flask, pandas, requests, SQLite (stdlib `sqlite3`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-23-nse-recommender-v1-design.md`

## Global Constraints

- EOD bhavcopy only — no real-time/intraday data.
- Cash-market equities only: keep rows where `SctySrs == "EQ"`. No F&O/derivatives.
- Recommendations only ever consider symbols in the bundled Nifty 500 list.
- Exactly top-5 buy + bottom-5 sell picks per horizon. No volume filter (explicitly dropped during design).
- Horizon lookback/target/stop-loss bands (off entry): short-term 3 trading days (+5%/-2.5%), mid-term 10 trading days (+10%/-5%), long-term 40 trading days (+20%/-10%).
- Insufficient data must degrade to an explicit per-horizon message — never a blank list or a crash.
- Bhavcopy downloads must be idempotent (safe to re-run) and must never silently retry forever on failure — each date's outcome (success/no_data/failed) is logged once and reused.
- NSE bhavcopy requests must send a browser-like `User-Agent` and `Referer` header — NSE's WAF blackholes default library user agents (confirmed in the prior project).
- Past Picks is a raw per-pick outcome log only — no aggregate win-rate stats in V1.
- Single local process (Flask + SQLite). No deployment/hosting work in V1 (see spec's "Hosting" section — deferred).

---

## File Structure

```
nse-recommender-v2/
├── app.py                         # Flask app factory + routes
├── requirements.txt
├── README.md
├── .gitignore
├── nse_recommender/
│   ├── __init__.py
│   ├── db.py                      # SQLite schema + connection helper
│   ├── calendar_nse.py            # weekday candidate-day generation for range labels
│   ├── downloader.py              # bhavcopy fetch/parse/store + download orchestration
│   ├── universe.py                # Nifty 500 list fetch/save/load
│   ├── status.py                  # download coverage summary
│   ├── recommender.py             # ranking engine + recommendation persistence
│   └── outcomes.py                # past-pick outcome computation
├── data/
│   └── nifty500_list.csv          # fetched once via scripts/fetch_universe.py, committed
├── scripts/
│   └── fetch_universe.py          # one-off CLI to (re)populate data/nifty500_list.csv
├── templates/
│   ├── base.html
│   ├── index.html
│   ├── recommendations.html
│   └── past_picks.html
└── tests/
    ├── test_db.py
    ├── test_calendar_nse.py
    ├── test_downloader.py
    ├── test_universe.py
    ├── test_status.py
    ├── test_recommender.py
    ├── test_outcomes.py
    └── test_integration.py
```

---

### Task 1: Project scaffolding & database schema

**Files:**
- Create: `requirements.txt`, `.gitignore`, `nse_recommender/__init__.py`, `nse_recommender/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `db.DB_PATH: Path`, `db.get_connection(db_path=None) -> sqlite3.Connection` (row_factory set to `sqlite3.Row`), `db.init_db(conn) -> None` (creates `bhavcopy_prices`, `downloads_log`, `recommendations` tables if not present).

- [ ] **Step 1: Create the project skeleton**

```bash
mkdir -p nse_recommender data scripts templates tests
touch nse_recommender/__init__.py
```

Create `requirements.txt`:

```
Flask==3.0.3
pandas==2.2.2
requests==2.32.3
pytest==8.2.2
```

Create `.gitignore`:

```
__pycache__/
*.pyc
.venv/
nse.db
test_nse.db
```

Set up and activate a virtualenv, then install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

- [ ] **Step 2: Write the failing test**

`tests/test_db.py`:

```python
import sqlite3

from nse_recommender.db import get_connection, init_db


def test_init_db_creates_expected_tables():
    conn = get_connection(":memory:")
    init_db(conn)
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"bhavcopy_prices", "downloads_log", "recommendations"} <= tables


def test_get_connection_uses_row_factory():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute(
        "INSERT INTO downloads_log (date, status, message, fetched_at) VALUES (?,?,?,?)",
        ("2026-01-01", "success", "1 symbols", "2026-01-01T00:00:00"),
    )
    row = conn.execute("SELECT * FROM downloads_log").fetchone()
    assert row["date"] == "2026-01-01"
    assert isinstance(row, sqlite3.Row)


def test_init_db_is_idempotent():
    conn = get_connection(":memory:")
    init_db(conn)
    init_db(conn)  # must not raise
```

- [ ] **Step 3: Run the tests and verify they fail**

Run: `pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nse_recommender.db'`

- [ ] **Step 4: Implement `nse_recommender/db.py`**

```python
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "nse.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS bhavcopy_prices (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS downloads_log (
    date TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    message TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    horizon TEXT NOT NULL,
    side TEXT NOT NULL,
    generated_date TEXT NOT NULL,
    entry REAL NOT NULL,
    target REAL NOT NULL,
    stop_loss REAL NOT NULL
);
"""


def get_connection(db_path=None):
    conn = sqlite3.connect(str(db_path) if db_path is not None else str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    conn.executescript(SCHEMA)
    conn.commit()
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add requirements.txt .gitignore nse_recommender/__init__.py nse_recommender/db.py tests/test_db.py
git commit -m "Add project scaffolding and SQLite schema"
```

---

### Task 2: NSE trading-day calendar

**Files:**
- Create: `nse_recommender/calendar_nse.py`
- Test: `tests/test_calendar_nse.py`

**Interfaces:**
- Consumes: nothing (pure `datetime.date` logic).
- Produces: `calendar_nse.candidate_days(start: date, end: date) -> list[date]`, `calendar_nse.range_for_label(label: str, today: date) -> list[date]` (labels: `"yesterday"`, `"this_month"`, `"last_month"`, `"last_6_months"`; raises `ValueError` on unknown label).

- [ ] **Step 1: Write the failing test**

`tests/test_calendar_nse.py`:

```python
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_calendar_nse.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nse_recommender.calendar_nse'`

- [ ] **Step 3: Implement `nse_recommender/calendar_nse.py`**

```python
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
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_calendar_nse.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add nse_recommender/calendar_nse.py tests/test_calendar_nse.py
git commit -m "Add NSE trading-day candidate calendar"
```

---

### Task 3: BhavCopy fetch & parse

**Files:**
- Create: `nse_recommender/downloader.py`
- Test: `tests/test_downloader.py`

**Interfaces:**
- Consumes: `db.get_connection`, `db.init_db` (for the storage test).
- Produces: `downloader.NoDataForDate` (exception), `downloader.build_url(d: date) -> str`, `downloader.fetch_bhavcopy_csv(d: date, session=None) -> str` (raises `NoDataForDate` on HTTP 404), `downloader.parse_bhavcopy_csv(csv_text: str, allowed_symbols: set[str]) -> list[dict]` (each dict has keys `symbol, date, open, high, low, close, volume`), `downloader.store_bhavcopy_rows(conn, rows: list[dict]) -> None` (idempotent upsert).

**Note on data format:** these column names (`TckrSymb`, `SctySrs`, `OpnPric`, `HghPric`, `LwPric`, `ClsPric`, `TtlTradgVol`, `TradDt`) and the URL pattern below are carried forward verbatim from the prior project's verified-working implementation (`~/nse-stock-recommender`) — NSE migrated formats once already (mid-2024) and this is the current live one.

- [ ] **Step 1: Write the failing test**

`tests/test_downloader.py`:

```python
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_downloader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nse_recommender.downloader'`

- [ ] **Step 3: Implement `nse_recommender/downloader.py`**

```python
import csv
import io
import zipfile

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
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_downloader.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add nse_recommender/downloader.py tests/test_downloader.py
git commit -m "Add bhavcopy fetch and parse logic"
```

---

### Task 4: Download orchestration

**Files:**
- Modify: `nse_recommender/downloader.py`
- Modify: `tests/test_downloader.py`

**Interfaces:**
- Consumes: `NoDataForDate`, `fetch_bhavcopy_csv`, `parse_bhavcopy_csv`, `store_bhavcopy_rows` (all from Task 3, same file).
- Produces: `downloader.download_missing_days(conn, dates: list[date], allowed_symbols: set[str], fetch_fn=None) -> dict` returning `{"success": [...], "no_data": [...], "failed": [...]}` (lists of ISO date strings). Looks up the module-level `fetch_bhavcopy_csv` dynamically when `fetch_fn` is `None`, so tests (and callers) can monkeypatch it.

**Important implementation detail:** the default fetch function must be resolved *inside* the function body (`fetch_fn if fetch_fn is not None else fetch_bhavcopy_csv`), not as a literal default-argument value (`fetch_fn=fetch_bhavcopy_csv`) — a default-argument value is bound once at module load time, so `monkeypatch.setattr(downloader, "fetch_bhavcopy_csv", fake)` would silently fail to affect callers that don't pass `fetch_fn` explicitly (this matters for Task 9's Flask routes, which call this function without `fetch_fn`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_downloader.py`:

```python
from datetime import date as date_cls


def test_download_missing_days_buckets_success_no_data_and_failed():
    conn = get_connection(":memory:")
    init_db(conn)

    def fake_fetch(d, session=None):
        if d == date_cls(2026, 9, 18):
            return SAMPLE_CSV.replace("2026-09-20", "2026-09-18")
        if d == date_cls(2026, 9, 19):
            raise downloader.NoDataForDate("holiday")
        raise RuntimeError("network down")

    results = downloader.download_missing_days(
        conn,
        [date_cls(2026, 9, 18), date_cls(2026, 9, 19), date_cls(2026, 9, 21)],
        allowed_symbols={"RELIANCE", "TCS"},
        fetch_fn=fake_fetch,
    )
    assert results["success"] == ["2026-09-18"]
    assert results["no_data"] == ["2026-09-19"]
    assert results["failed"] == ["2026-09-21"]


def test_download_missing_days_skips_already_downloaded_dates():
    conn = get_connection(":memory:")
    init_db(conn)
    calls = []

    def fake_fetch(d, session=None):
        calls.append(d)
        return SAMPLE_CSV

    downloader.download_missing_days(conn, [date_cls(2026, 9, 18)], {"RELIANCE"}, fetch_fn=fake_fetch)
    downloader.download_missing_days(conn, [date_cls(2026, 9, 18)], {"RELIANCE"}, fetch_fn=fake_fetch)
    assert calls == [date_cls(2026, 9, 18)]


def test_download_missing_days_uses_module_level_fetch_when_not_overridden(monkeypatch):
    conn = get_connection(":memory:")
    init_db(conn)

    def fake_fetch(d, session=None):
        raise downloader.NoDataForDate("patched")

    monkeypatch.setattr(downloader, "fetch_bhavcopy_csv", fake_fetch)
    results = downloader.download_missing_days(conn, [date_cls(2026, 9, 18)], {"RELIANCE"})
    assert results["no_data"] == ["2026-09-18"]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_downloader.py -v`
Expected: FAIL with `AttributeError: module 'nse_recommender.downloader' has no attribute 'download_missing_days'`

- [ ] **Step 3: Add orchestration to `nse_recommender/downloader.py`**

Append to the file (add `from datetime import datetime` to the imports at the top):

```python
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
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_downloader.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add nse_recommender/downloader.py tests/test_downloader.py
git commit -m "Add idempotent download orchestration with success/no_data/failed tracking"
```

---

### Task 5: Nifty 500 universe loader

**Files:**
- Create: `nse_recommender/universe.py`, `scripts/fetch_universe.py`
- Test: `tests/test_universe.py`

**Interfaces:**
- Produces: `universe.UNIVERSE_PATH: Path`, `universe.fetch_nifty500_csv(session=None) -> str`, `universe.save_universe_csv(csv_text: str, path=None) -> None`, `universe.load_nifty500_symbols(path=None) -> list[str]`.

**Note on data source:** URL carried forward from the prior project's `UniverseDownloader.kt` (`https://niftyindices.com/IndexConstituent/ind_nifty500list.csv`), which returns a CSV with a `Symbol` column.

- [ ] **Step 1: Write the failing test**

`tests/test_universe.py`:

```python
from nse_recommender import universe

SAMPLE_UNIVERSE_CSV = (
    "Company Name,Industry,Symbol,Series,ISIN Code\n"
    "Reliance Industries Ltd.,Energy,RELIANCE,EQ,INE002A01018\n"
    "Tata Consultancy Services Ltd.,IT,TCS,EQ,INE467B01029\n"
)


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, text):
        self._text = text

    def get(self, url, headers=None, timeout=None):
        return FakeResponse(self._text)


def test_fetch_nifty500_csv_returns_response_text():
    session = FakeSession(SAMPLE_UNIVERSE_CSV)
    text = universe.fetch_nifty500_csv(session=session)
    assert "RELIANCE" in text


def test_save_and_load_universe_round_trip(tmp_path):
    path = tmp_path / "nifty500_list.csv"
    universe.save_universe_csv(SAMPLE_UNIVERSE_CSV, path=path)
    symbols = universe.load_nifty500_symbols(path=path)
    assert symbols == ["RELIANCE", "TCS"]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_universe.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nse_recommender.universe'`

- [ ] **Step 3: Implement `nse_recommender/universe.py`**

```python
import csv
from pathlib import Path

import requests

NIFTY500_URL = "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv"
UNIVERSE_PATH = Path(__file__).resolve().parent.parent / "data" / "nifty500_list.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NseRecommenderV1/1.0)"}


def fetch_nifty500_csv(session=None):
    getter = session.get if session is not None else requests.get
    resp = getter(NIFTY500_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def save_universe_csv(csv_text, path=None):
    target = Path(path) if path is not None else UNIVERSE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(csv_text)


def load_nifty500_symbols(path=None):
    target = Path(path) if path is not None else UNIVERSE_PATH
    with target.open(newline="") as f:
        reader = csv.DictReader(f)
        return [row["Symbol"].strip() for row in reader if row.get("Symbol")]
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_universe.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Create the fetch script**

`scripts/fetch_universe.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nse_recommender import universe


def main():
    csv_text = universe.fetch_nifty500_csv()
    universe.save_universe_csv(csv_text)
    symbols = universe.load_nifty500_symbols()
    print(f"Saved {len(symbols)} Nifty 500 symbols to {universe.UNIVERSE_PATH}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the script for real to populate the universe file**

```bash
python scripts/fetch_universe.py
```

Expected: prints `Saved N Nifty 500 symbols to .../data/nifty500_list.csv` with N close to 500. If this fails (network/WAF block), see the spec's note that this URL was not fully re-verified in the prior project — try fetching `https://niftyindices.com/IndexConstituent/ind_nifty500list.csv` directly in a browser, save the downloaded file to `data/nifty500_list.csv` manually, and re-run `load_nifty500_symbols()` to confirm it parses.

- [ ] **Step 7: Commit**

```bash
git add nse_recommender/universe.py scripts/fetch_universe.py tests/test_universe.py data/nifty500_list.csv
git commit -m "Add Nifty 500 universe fetch/load and bundle the current list"
```

---

### Task 6: Download coverage status

**Files:**
- Create: `nse_recommender/status.py`
- Test: `tests/test_status.py`

**Interfaces:**
- Consumes: `calendar_nse.range_for_label`.
- Produces: `status.RANGE_LABELS: list[str]`, `status.coverage_summary(conn, today: date) -> dict` shaped as `{"earliest_date": str|None, "latest_date": str|None, "total_days": int, "ranges": {label: {"expected": int, "present": int}}}`.

- [ ] **Step 1: Write the failing test**

`tests/test_status.py`:

```python
from datetime import date

from nse_recommender import status
from nse_recommender.db import get_connection, init_db


def _insert_price(conn, symbol, d):
    conn.execute(
        "INSERT INTO bhavcopy_prices (symbol, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
        (symbol, d.isoformat(), 100, 100, 100, 100, 1000),
    )


def test_coverage_summary_with_no_data():
    conn = get_connection(":memory:")
    init_db(conn)
    summary = status.coverage_summary(conn, date(2024, 1, 16))
    assert summary["earliest_date"] is None
    assert summary["latest_date"] is None
    assert summary["total_days"] == 0
    assert summary["ranges"]["yesterday"] == {"expected": 1, "present": 0}


def test_coverage_summary_reflects_downloaded_and_holiday_days():
    conn = get_connection(":memory:")
    init_db(conn)
    today = date(2024, 1, 16)  # Tuesday; yesterday = Monday Jan 15
    _insert_price(conn, "RELIANCE", date(2024, 1, 15))
    conn.execute(
        "INSERT INTO downloads_log (date, status, message, fetched_at) VALUES (?,?,?,?)",
        ("2024-01-12", "no_data", None, "2024-01-16T00:00:00"),
    )
    conn.commit()

    summary = status.coverage_summary(conn, today)

    assert summary["earliest_date"] == "2024-01-15"
    assert summary["latest_date"] == "2024-01-15"
    assert summary["total_days"] == 1
    assert summary["ranges"]["yesterday"] == {"expected": 1, "present": 1}
    # this_month candidate weekdays: Jan 1-5, 8-12, 15, 16 = 12 weekdays;
    # Jan 12 confirmed no_data (holiday) -> expected = 11; only Jan 15 present.
    assert summary["ranges"]["this_month"] == {"expected": 11, "present": 1}
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_status.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nse_recommender.status'`

- [ ] **Step 3: Implement `nse_recommender/status.py`**

```python
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
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_status.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add nse_recommender/status.py tests/test_status.py
git commit -m "Add download coverage summary"
```

---

### Task 7: Recommendation engine

**Files:**
- Create: `nse_recommender/recommender.py`
- Test: `tests/test_recommender.py`

**Interfaces:**
- Produces: `recommender.HORIZONS: dict` (keys `"short_term"`, `"mid_term"`, `"long_term"`, each with `label`, `lookback_days`, `target_pct`, `stop_loss_pct`), `recommender.InsufficientData(have, need)` (exception with `.have`/`.need` attributes), `recommender.compute_returns(conn, symbols, lookback_days) -> pandas.DataFrame` (columns `symbol, entry, base, pct_return`, sorted descending by `pct_return`), `recommender.generate_recommendations(conn, symbols, horizon_key) -> dict` (either `{"status": "ok", "label": str, "buy": [...5 picks], "sell": [...5 picks]}` or `{"status": "insufficient_data", "have": int, "need": int, "label": str}`; each pick is `{"symbol", "entry", "target", "stop_loss", "reason"}`), `recommender.save_recommendations(conn, horizon_key, generated_date, result) -> None`, `recommender.generate_and_save_all(conn, symbols, generated_date) -> dict[str, dict]` (one result per horizon key, saving each `"ok"` result).

- [ ] **Step 1: Write the failing test**

`tests/test_recommender.py`:

```python
from datetime import date, timedelta

import pytest

from nse_recommender import recommender
from nse_recommender.db import get_connection, init_db

DATES = [date(2024, 1, 1) + timedelta(days=i) for i in range(11)]
SYMBOLS = [f"SYM{i:02d}" for i in range(12)]
FINAL_RETURNS = {SYMBOLS[i]: (i - 5) * 0.02 for i in range(12)}  # -0.10 .. +0.12


def _close_at(symbol, date_index):
    ret = FINAL_RETURNS[symbol]
    return 100 * (1 + ret * (date_index / 10))


@pytest.fixture
def seeded_conn():
    conn = get_connection(":memory:")
    init_db(conn)
    rows = []
    for date_index, d in enumerate(DATES):
        for symbol in SYMBOLS:
            close = _close_at(symbol, date_index)
            rows.append({
                "symbol": symbol, "date": d.isoformat(), "open": close, "high": close,
                "low": close, "close": close, "volume": 1000,
            })
    conn.executemany(
        """INSERT INTO bhavcopy_prices (symbol, date, open, high, low, close, volume)
           VALUES (:symbol, :date, :open, :high, :low, :close, :volume)""",
        rows,
    )
    conn.commit()
    return conn


def test_compute_returns_ranks_symbols_by_pct_change(seeded_conn):
    ranked = recommender.compute_returns(seeded_conn, SYMBOLS, lookback_days=10)
    assert ranked.iloc[0]["symbol"] == "SYM11"
    assert ranked.iloc[-1]["symbol"] == "SYM00"


def test_compute_returns_raises_when_not_enough_history(seeded_conn):
    with pytest.raises(recommender.InsufficientData) as excinfo:
        recommender.compute_returns(seeded_conn, SYMBOLS, lookback_days=40)
    assert excinfo.value.have == 11
    assert excinfo.value.need == 41


def test_generate_recommendations_short_term_returns_top5_buy_and_bottom5_sell(seeded_conn):
    result = recommender.generate_recommendations(seeded_conn, SYMBOLS, "short_term")
    assert result["status"] == "ok"
    assert [p["symbol"] for p in result["buy"]] == ["SYM11", "SYM10", "SYM09", "SYM08", "SYM07"]
    assert [p["symbol"] for p in result["sell"]] == ["SYM00", "SYM01", "SYM02", "SYM03", "SYM04"]


def test_generate_recommendations_buy_pick_target_and_stop_loss(seeded_conn):
    result = recommender.generate_recommendations(seeded_conn, SYMBOLS, "short_term")
    top_pick = result["buy"][0]
    entry = top_pick["entry"]
    assert top_pick["target"] == round(entry * 1.05, 2)
    assert top_pick["stop_loss"] == round(entry * 0.975, 2)


def test_generate_recommendations_sell_pick_target_below_entry(seeded_conn):
    result = recommender.generate_recommendations(seeded_conn, SYMBOLS, "short_term")
    top_sell = result["sell"][0]
    assert top_sell["target"] < top_sell["entry"] < top_sell["stop_loss"]


def test_generate_recommendations_long_term_reports_insufficient_data(seeded_conn):
    result = recommender.generate_recommendations(seeded_conn, SYMBOLS, "long_term")
    assert result["status"] == "insufficient_data"
    assert result["have"] == 11
    assert result["need"] == 41
    assert "label" in result


def test_generate_and_save_all_persists_ok_horizons_only(seeded_conn):
    recommender.generate_and_save_all(seeded_conn, SYMBOLS, generated_date="2024-01-11")
    rows = seeded_conn.execute("SELECT DISTINCT horizon FROM recommendations").fetchall()
    horizons_saved = {r["horizon"] for r in rows}
    assert horizons_saved == {"short_term", "mid_term"}
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_recommender.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nse_recommender.recommender'`

- [ ] **Step 3: Implement `nse_recommender/recommender.py`**

```python
import pandas as pd

HORIZONS = {
    "short_term": {"label": "Short-term (3 trading days)", "lookback_days": 3, "target_pct": 0.05, "stop_loss_pct": 0.025},
    "mid_term": {"label": "Mid-term (~2 weeks)", "lookback_days": 10, "target_pct": 0.10, "stop_loss_pct": 0.05},
    "long_term": {"label": "Long-term (~2 months)", "lookback_days": 40, "target_pct": 0.20, "stop_loss_pct": 0.10},
}


class InsufficientData(Exception):
    def __init__(self, have, need):
        self.have = have
        self.need = need
        super().__init__(f"Have {have} trading days of data, need {need}")


def compute_returns(conn, symbols, lookback_days):
    if not symbols:
        raise InsufficientData(have=0, need=lookback_days + 1)
    placeholders = ",".join("?" * len(symbols))
    df = pd.read_sql_query(
        f"SELECT symbol, date, close FROM bhavcopy_prices WHERE symbol IN ({placeholders}) ORDER BY date",
        conn,
        params=symbols,
    )
    all_dates = sorted(df["date"].unique())
    if len(all_dates) < lookback_days + 1:
        raise InsufficientData(have=len(all_dates), need=lookback_days + 1)
    latest_date = all_dates[-1]
    base_date = all_dates[-(lookback_days + 1)]
    latest = df[df["date"] == latest_date].set_index("symbol")["close"]
    base = df[df["date"] == base_date].set_index("symbol")["close"]
    joined = latest.to_frame("entry").join(base.to_frame("base"), how="inner")
    joined["pct_return"] = (joined["entry"] - joined["base"]) / joined["base"]
    return joined.reset_index().sort_values("pct_return", ascending=False).reset_index(drop=True)


def _levels(entry, side, target_pct, stop_loss_pct):
    if side == "buy":
        return entry * (1 + target_pct), entry * (1 - stop_loss_pct)
    return entry * (1 - target_pct), entry * (1 + stop_loss_pct)


def _build_picks(rows, side, config):
    picks = []
    for _, row in rows.iterrows():
        target, stop_loss = _levels(row["entry"], side, config["target_pct"], config["stop_loss_pct"])
        pct = row["pct_return"] * 100
        picks.append({
            "symbol": row["symbol"],
            "entry": round(row["entry"], 2),
            "target": round(target, 2),
            "stop_loss": round(stop_loss, 2),
            "reason": f"{pct:+.1f}% over last {config['lookback_days']} trading days",
        })
    return picks


def generate_recommendations(conn, symbols, horizon_key):
    config = HORIZONS[horizon_key]
    try:
        ranked = compute_returns(conn, symbols, config["lookback_days"])
    except InsufficientData as exc:
        return {"status": "insufficient_data", "have": exc.have, "need": exc.need, "label": config["label"]}
    top5 = ranked.head(5)
    bottom5 = ranked.tail(5).iloc[::-1]
    return {
        "status": "ok",
        "label": config["label"],
        "buy": _build_picks(top5, "buy", config),
        "sell": _build_picks(bottom5, "sell", config),
    }


def save_recommendations(conn, horizon_key, generated_date, result):
    if result["status"] != "ok":
        return
    for side in ("buy", "sell"):
        for pick in result[side]:
            conn.execute(
                """INSERT INTO recommendations (symbol, horizon, side, generated_date, entry, target, stop_loss)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (pick["symbol"], horizon_key, side, generated_date, pick["entry"], pick["target"], pick["stop_loss"]),
            )
    conn.commit()


def generate_and_save_all(conn, symbols, generated_date):
    results = {}
    for horizon_key in HORIZONS:
        result = generate_recommendations(conn, symbols, horizon_key)
        save_recommendations(conn, horizon_key, generated_date, result)
        results[horizon_key] = result
    return results
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_recommender.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add nse_recommender/recommender.py tests/test_recommender.py
git commit -m "Add momentum-based recommendation engine with persistence"
```

---

### Task 8: Past-picks outcome tracking

**Files:**
- Create: `nse_recommender/outcomes.py`
- Test: `tests/test_outcomes.py`

**Interfaces:**
- Produces: `outcomes.compute_outcome(conn, rec: dict) -> dict` (`{"status": "target_hit"|"stop_loss_hit"|"still_open", "as_of_date": str, "current_price": float}`; `rec` must have keys `symbol, generated_date, side, entry, target, stop_loss` — a `recommendations` table row works directly), `outcomes.list_past_picks(conn) -> list[dict]` (each dict merges the recommendation row with its outcome, most recent `generated_date` first).

- [ ] **Step 1: Write the failing test**

`tests/test_outcomes.py`:

```python
from datetime import date, timedelta

from nse_recommender import outcomes
from nse_recommender.db import get_connection, init_db


def _insert_price(conn, symbol, d, close):
    conn.execute(
        "INSERT INTO bhavcopy_prices (symbol, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
        (symbol, d.isoformat(), close, close, close, close, 1000),
    )
    conn.commit()


def _insert_recommendation(conn, symbol, side, generated_date, entry, target, stop_loss):
    conn.execute(
        """INSERT INTO recommendations (symbol, horizon, side, generated_date, entry, target, stop_loss)
           VALUES (?, 'short_term', ?, ?, ?, ?, ?)""",
        (symbol, side, generated_date, entry, target, stop_loss),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM recommendations WHERE symbol = ?", (symbol,)).fetchone())


def test_compute_outcome_detects_target_hit_for_buy_pick():
    conn = get_connection(":memory:")
    init_db(conn)
    base = date(2026, 1, 1)
    rec = _insert_recommendation(conn, "RELIANCE", "buy", base.isoformat(), 100, 105, 95)
    _insert_price(conn, "RELIANCE", base + timedelta(days=1), 102)
    _insert_price(conn, "RELIANCE", base + timedelta(days=2), 106)
    outcome = outcomes.compute_outcome(conn, rec)
    assert outcome["status"] == "target_hit"
    assert outcome["current_price"] == 106


def test_compute_outcome_detects_stop_loss_hit_for_buy_pick():
    conn = get_connection(":memory:")
    init_db(conn)
    base = date(2026, 1, 1)
    rec = _insert_recommendation(conn, "RELIANCE", "buy", base.isoformat(), 100, 105, 95)
    _insert_price(conn, "RELIANCE", base + timedelta(days=1), 94)
    outcome = outcomes.compute_outcome(conn, rec)
    assert outcome["status"] == "stop_loss_hit"


def test_compute_outcome_still_open_with_no_later_data():
    conn = get_connection(":memory:")
    init_db(conn)
    base = date(2026, 1, 1)
    rec = _insert_recommendation(conn, "RELIANCE", "buy", base.isoformat(), 100, 105, 95)
    outcome = outcomes.compute_outcome(conn, rec)
    assert outcome["status"] == "still_open"
    assert outcome["current_price"] == 100


def test_compute_outcome_still_open_with_later_data_between_bands():
    conn = get_connection(":memory:")
    init_db(conn)
    base = date(2026, 1, 1)
    rec = _insert_recommendation(conn, "RELIANCE", "buy", base.isoformat(), 100, 105, 95)
    _insert_price(conn, "RELIANCE", base + timedelta(days=1), 101)
    outcome = outcomes.compute_outcome(conn, rec)
    assert outcome["status"] == "still_open"
    assert outcome["current_price"] == 101


def test_compute_outcome_sell_pick_target_is_price_falling():
    conn = get_connection(":memory:")
    init_db(conn)
    base = date(2026, 1, 1)
    rec = _insert_recommendation(conn, "TCS", "sell", base.isoformat(), 100, 90, 110)
    _insert_price(conn, "TCS", base + timedelta(days=1), 89)
    outcome = outcomes.compute_outcome(conn, rec)
    assert outcome["status"] == "target_hit"


def test_list_past_picks_orders_most_recent_first():
    conn = get_connection(":memory:")
    init_db(conn)
    _insert_recommendation(conn, "OLD", "buy", "2026-01-01", 100, 105, 95)
    _insert_recommendation(conn, "NEW", "buy", "2026-02-01", 100, 105, 95)
    picks = outcomes.list_past_picks(conn)
    assert [p["symbol"] for p in picks] == ["NEW", "OLD"]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_outcomes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nse_recommender.outcomes'`

- [ ] **Step 3: Implement `nse_recommender/outcomes.py`**

```python
def compute_outcome(conn, rec):
    cur = conn.execute(
        "SELECT date, close FROM bhavcopy_prices WHERE symbol = ? AND date > ? ORDER BY date ASC",
        (rec["symbol"], rec["generated_date"]),
    )
    later_prices = cur.fetchall()
    for row in later_prices:
        close = row["close"]
        if rec["side"] == "buy":
            if close >= rec["target"]:
                return {"status": "target_hit", "as_of_date": row["date"], "current_price": close}
            if close <= rec["stop_loss"]:
                return {"status": "stop_loss_hit", "as_of_date": row["date"], "current_price": close}
        else:
            if close <= rec["target"]:
                return {"status": "target_hit", "as_of_date": row["date"], "current_price": close}
            if close >= rec["stop_loss"]:
                return {"status": "stop_loss_hit", "as_of_date": row["date"], "current_price": close}
    if later_prices:
        last = later_prices[-1]
        return {"status": "still_open", "as_of_date": last["date"], "current_price": last["close"]}
    return {"status": "still_open", "as_of_date": rec["generated_date"], "current_price": rec["entry"]}


def list_past_picks(conn):
    rows = conn.execute(
        "SELECT * FROM recommendations ORDER BY generated_date DESC, id DESC"
    ).fetchall()
    picks = []
    for row in rows:
        rec = dict(row)
        outcome = compute_outcome(conn, rec)
        picks.append({**rec, **outcome})
    return picks
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_outcomes.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add nse_recommender/outcomes.py tests/test_outcomes.py
git commit -m "Add past-pick outcome tracking (target/stop-loss/still open)"
```

---

### Task 9: Flask web app

**Files:**
- Create: `app.py`, `templates/base.html`, `templates/index.html`, `templates/recommendations.html`, `templates/past_picks.html`
- Test: `tests/test_integration.py`

**Interfaces:**
- Consumes: `db`, `calendar_nse`, `downloader`, `universe`, `status`, `recommender`, `outcomes` (all prior tasks).
- Produces: `app.create_app(db_path=None, symbols=None) -> Flask` — routes `GET /`, `POST /download/<label>`, `GET /recommendations`, `GET /past-picks`.

- [ ] **Step 1: Write the failing integration test**

`tests/test_integration.py`:

```python
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_integration.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Implement the templates**

`templates/base.html`:

```html
<!doctype html>
<html>
<head><title>NSE Recommender</title></head>
<body>
<nav>
  <a href="{{ url_for('index') }}">Downloader</a> |
  <a href="{{ url_for('recommendations') }}">Recommendations</a> |
  <a href="{{ url_for('past_picks') }}">Past Picks</a>
</nav>
<hr>
{% block content %}{% endblock %}
</body>
</html>
```

`templates/index.html`:

```html
{% extends "base.html" %}
{% block content %}
<h1>BhavCopy Downloader</h1>
<form method="post" action="{{ url_for('download', label='yesterday') }}"><button>Yesterday</button></form>
<form method="post" action="{{ url_for('download', label='this_month') }}"><button>This Month</button></form>
<form method="post" action="{{ url_for('download', label='last_month') }}"><button>Last Month</button></form>
<form method="post" action="{{ url_for('download', label='last_6_months') }}"><button>Last 6 Months</button></form>

<h2>Coverage</h2>
<p>Earliest date: {{ coverage.earliest_date or "none" }}</p>
<p>Latest date: {{ coverage.latest_date or "none" }}</p>
<p>Total trading days stored: {{ coverage.total_days }}</p>
<table border="1">
<tr><th>Range</th><th>Present</th><th>Expected</th></tr>
{% for label, info in coverage.ranges.items() %}
<tr><td>{{ label }}</td><td>{{ info.present }}</td><td>{{ info.expected }}</td></tr>
{% endfor %}
</table>
{% endblock %}
```

`templates/recommendations.html`:

```html
{% extends "base.html" %}
{% block content %}
<h1>Recommendations ({{ generated_date }})</h1>
{% for horizon_key, result in results.items() %}
<h2>{{ result.label }}</h2>
{% if result.status == "insufficient_data" %}
<p>Need {{ result.need }} trading days of data, have {{ result.have }} &mdash; download more history first.</p>
{% else %}
<h3>Buy</h3>
<table border="1"><tr><th>Symbol</th><th>Entry</th><th>Target</th><th>Stop-loss</th><th>Reason</th></tr>
{% for pick in result.buy %}
<tr><td>{{ pick.symbol }}</td><td>{{ pick.entry }}</td><td>{{ pick.target }}</td><td>{{ pick.stop_loss }}</td><td>{{ pick.reason }}</td></tr>
{% endfor %}
</table>
<h3>Sell</h3>
<table border="1"><tr><th>Symbol</th><th>Entry</th><th>Target</th><th>Stop-loss</th><th>Reason</th></tr>
{% for pick in result.sell %}
<tr><td>{{ pick.symbol }}</td><td>{{ pick.entry }}</td><td>{{ pick.target }}</td><td>{{ pick.stop_loss }}</td><td>{{ pick.reason }}</td></tr>
{% endfor %}
</table>
{% endif %}
{% endfor %}
{% endblock %}
```

`templates/past_picks.html`:

```html
{% extends "base.html" %}
{% block content %}
<h1>Past Picks</h1>
<table border="1">
<tr><th>Date</th><th>Horizon</th><th>Side</th><th>Symbol</th><th>Entry</th><th>Target</th><th>Stop-loss</th><th>Status</th><th>As of</th><th>Current price</th></tr>
{% for pick in picks %}
<tr>
<td>{{ pick.generated_date }}</td><td>{{ pick.horizon }}</td><td>{{ pick.side }}</td><td>{{ pick.symbol }}</td>
<td>{{ pick.entry }}</td><td>{{ pick.target }}</td><td>{{ pick.stop_loss }}</td>
<td>{{ pick.status }}</td><td>{{ pick.as_of_date }}</td><td>{{ pick.current_price }}</td>
</tr>
{% endfor %}
</table>
{% endblock %}
```

- [ ] **Step 4: Implement `app.py`**

```python
from datetime import date

from flask import Flask, current_app, redirect, render_template, url_for

from nse_recommender import calendar_nse, db, downloader, outcomes, recommender, status, universe


def create_app(db_path=None, symbols=None):
    app = Flask(__name__)
    resolved_db_path = db_path if db_path is not None else db.DB_PATH
    conn = db.get_connection(resolved_db_path)
    db.init_db(conn)
    conn.close()
    app.config["DB_PATH"] = resolved_db_path
    app.config["SYMBOLS"] = symbols if symbols is not None else universe.load_nifty500_symbols()

    @app.route("/")
    def index():
        conn = db.get_connection(current_app.config["DB_PATH"])
        try:
            coverage = status.coverage_summary(conn, date.today())
        finally:
            conn.close()
        return render_template("index.html", coverage=coverage)

    @app.route("/download/<label>", methods=["POST"])
    def download(label):
        conn = db.get_connection(current_app.config["DB_PATH"])
        try:
            dates = calendar_nse.range_for_label(label, date.today())
            downloader.download_missing_days(conn, dates, set(current_app.config["SYMBOLS"]))
        finally:
            conn.close()
        return redirect(url_for("index"))

    @app.route("/recommendations")
    def recommendations():
        conn = db.get_connection(current_app.config["DB_PATH"])
        try:
            generated_date = date.today().isoformat()
            results = recommender.generate_and_save_all(
                conn, current_app.config["SYMBOLS"], generated_date
            )
        finally:
            conn.close()
        return render_template("recommendations.html", results=results, generated_date=generated_date)

    @app.route("/past-picks")
    def past_picks():
        conn = db.get_connection(current_app.config["DB_PATH"])
        try:
            picks = outcomes.list_past_picks(conn)
        finally:
            conn.close()
        return render_template("past_picks.html", picks=picks)

    return app


if __name__ == "__main__":
    flask_app = create_app()
    flask_app.run(debug=True)
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `pytest tests/test_integration.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run the full test suite**

Run: `pytest -v`
Expected: PASS (all tests across all modules — roughly 43 tests)

- [ ] **Step 7: Commit**

```bash
git add app.py templates/ tests/test_integration.py
git commit -m "Add Flask web app wiring downloader, recommendations, and past picks"
```

---

### Task 10: README and manual verification

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# NSE Recommender V1

Local Flask + SQLite app that downloads NSE EOD bhavcopy data, ranks Nifty 500
stocks into short/mid/long-term buy & sell picks by price momentum, and
tracks whether past picks hit their target or stop-loss.

## Setup

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python scripts/fetch_universe.py   # one-time: populates data/nifty500_list.csv

## Run

    python app.py

Open http://localhost:5000 — start on the Downloader page and click at least
"Last 6 Months" before checking Recommendations (short/mid-term need 10-40
trading days of history; until then those horizons will say so explicitly).

## Test

    pytest -v
```

- [ ] **Step 2: Manual verification walkthrough**

Run the app and confirm the golden path works end to end:

```bash
python app.py
```

In a browser, visit `http://localhost:5000` and:
1. Click **Last 6 Months**. Confirm the page redirects back to the downloader and the coverage table shows non-zero "Present" counts.
2. Visit **Recommendations**. Confirm short-term and mid-term horizons show 5 buy + 5 sell picks with entry/target/stop-loss/reason; confirm long-term either shows picks (if 40+ trading days downloaded) or the explicit "download more history" message — never a blank section or an error page.
3. Visit **Past Picks**. Confirm the picks just generated appear, each with a `still_open` status (since they were generated today).
4. Click **Yesterday**, confirm no crash even if it's a holiday/weekend (coverage simply doesn't grow).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Add README with setup, run, and verification instructions"
```
