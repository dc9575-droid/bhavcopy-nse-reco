# NSE Stock Recommender V1 — Design Spec

**Date:** 2026-09-23
**Status:** Approved for planning
**Repo:** `~/nse-recommender-v2` (fresh, separate from the abandoned `~/nse-stock-recommender` Android project and from the `Garuda-The-Flying-Beast` repo where earlier design docs for this idea were drafted)

## Background

An earlier attempt at this idea was built as a native Android app (`~/nse-stock-recommender`). It reached a working V1 (buy/sell signals, short/mid-term horizons) but the user stopped there after a long debugging arc — Android emulator setup, an undocumented NSE bhavcopy format migration, and NSE's WAF silently blocking non-browser user agents. This spec starts over with a deliberately smaller, simpler stack to avoid repeating that arc, and a deliberately simpler signal algorithm ("from scratch", not a port of the old RSI/MACD/EMA logic).

## Goal

A very simple, very basic V1 that:
1. Downloads NSE EOD bhavcopy data for a chosen date range and shows what's actually been downloaded.
2. Analyzes Nifty 500 stocks and produces buy/sell recommendations across three horizons (short/mid/long term).
3. Logs its own recommendations and later shows whether each one hit its target, hit its stop-loss, or is still open — so the tool's track record is visible, not just its current picks.

## Non-goals (V1)

- No real-time/intraday data — EOD bhavcopy only.
- No F&O, options, or derivatives.
- No win-rate/aggregate performance stats — just the raw per-pick outcome log.
- No user accounts, no deployment — single local process for personal use.
- No porting of the old app's RSI/MACD/EMA signal logic — new, simpler logic (see below).

## Architecture

A single local Python process:
- **Flask** serves a small number of server-rendered HTML pages (no SPA/JS framework needed for this scope).
- **SQLite** (`nse.db`, file-based) stores downloaded bhavcopy rows and recommendation history. No external DB server.
- **pandas** handles CSV/zip parsing and the return-ranking math.

Run with `python app.py`; open `http://localhost:5000`. No background workers — downloads and recommendation generation happen synchronously on button click.

## Components

### 1. BhavCopy downloader

- UI: buttons for **Yesterday**, **This Month**, **Last Month**, **Last 6 Months**. Each click computes the set of NSE trading days in that range and downloads any bhavcopy files not already in the DB.
- Source: NSE's public bhavcopy archive (current UDiFF format at `nsearchives.nseindia.com`, per the format migration discovered in the prior attempt). Requests must send a browser-like User-Agent header — NSE's WAF blocks default library user agents.
- Each downloaded day is parsed into rows of (symbol, date, open, high, low, close, volume) and upserted into SQLite keyed by (symbol, date), so re-downloading the same day is a no-op, not a duplicate.
- Weekends/exchange holidays are skipped when computing "which days are missing" (a fixed NSE holiday list is bundled; if a date can't be downloaded — holiday or NSE has no file — it's marked as such, not silently retried forever).

### 2. Download status view

Same page as the downloader shows, from what's actually in SQLite:
- Earliest date, latest date, total trading days present.
- Per-range coverage, e.g. "Last 6 months: 118/126 trading days downloaded."
- This is a direct fix for the previous confusion around "is the bhavcopy actually up to date" — the app never claims freshness, it reports exactly what's stored.

### 3. Nifty 500 universe

A static CSV (`data/nifty500_list.csv`) bundled in the repo, containing the current Nifty 500 constituent symbols (from NSE's published list, captured at build time). All recommendation logic only considers symbols on this list. Refreshing this list is a manual, occasional file swap in V1 — not automated.

### 4. Recommendation engine

One shared ranking function parameterized by a lookback window in trading days, reused across all three horizons:

| Horizon | Lookback | Target / Stop-loss bands (off entry) |
|---|---|---|
| Short-term | 3 trading days | ±5% target / ±2.5% stop-loss |
| Mid-term | ~10 trading days (~2 weeks; configurable 1–4 weeks) | ±10% / ±5% |
| Long-term | ~40 trading days (~2 months; configurable 1–3 months) | ±20% / ±10% |

For each horizon:
- Compute % price return over the lookback window for every Nifty 500 symbol that has enough history in the DB (i.e. at least `lookback` trading days on record).
- Rank descending by return. **Top 5 → Buy picks** (bullish momentum), **bottom 5 → Sell picks** (bearish momentum).
- No volume filter in V1 (considered and explicitly dropped — pure price-return ranking only).
- Each pick displays: symbol, entry (latest close in DB), target price, stop-loss price, and a plain-language reason (e.g. "+6.2% over last 3 trading days").
- If fewer than `lookback` trading days of history exist for a horizon, that horizon's section says so explicitly (e.g. "Need 10 trading days of data, have 4 — download more history") rather than showing an empty or misleading list.

### 5. Outcome tracking (self-recommendation log)

- Every time recommendations are generated for a horizon, the 10 picks (5 buy + 5 sell) are persisted to a `recommendations` table: symbol, horizon, side (buy/sell), generated date, entry, target, stop-loss.
- A separate **Past Picks** page lists all historical picks, and for each one — using whatever later bhavcopy data now exists in the DB — computes and displays status:
  - **Target hit** — a later close reached the target price before hitting the stop-loss.
  - **Stop-loss hit** — a later close reached the stop-loss price before hitting the target.
  - **Still open** — neither has happened yet with current data; shows current price vs. entry.
- This is a plain log, not a dashboard — no win-rate percentages or aggregate stats in V1.

## Data flow

```
NSE bhavcopy archive → downloader (parse) → SQLite (bhavcopy_prices)
                                                     ↓
                          Nifty 500 list (static CSV) → recommendation engine
                                                     ↓
                                    recommendations table (persisted picks)
                                                     ↓
                              Past Picks page (re-reads bhavcopy_prices for outcome)
```

## Error handling

- Download failures (network error, WAF block, missing file for a given date) are caught per-day and surfaced in the status view as "failed" for that date, not silently dropped or retried in a loop.
- Recommendation generation on insufficient data degrades to an explicit per-horizon message (see Component 4), never a crash or a blank page.

## Testing

- Unit tests for the bhavcopy parser: given a sample CSV, verify correct row extraction.
- Unit tests for the ranking function: given a known synthetic price series, verify correct ranking order and target/stop-loss math for each horizon.
- One integration test: download a small fixed historical date range (already-published, stable data), confirm expected row counts in SQLite and that recommendation generation produces output without error.

## Open items for the implementation plan

- Exact NSE bhavcopy URL pattern and holiday list source (carry forward the working logic already discovered in the prior attempt, since this part was hard-won and is not being redesigned).
- Confirm target/stop-loss band percentages above are reasonable starting defaults (easy to tune later, not a structural decision).
