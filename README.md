# NSE Recommender V1

Local Flask + SQLite app that downloads NSE EOD bhavcopy data, ranks Nifty 500
stocks into short/mid/long-term buy & sell picks by price momentum, and
tracks whether past picks hit their target or stop-loss.

## Setup

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

`data/nifty500_list.csv` is already bundled in the repo, so no extra setup
step is needed to get started. `python scripts/fetch_universe.py` exists only
to *refresh* that list later — it isn't required for initial setup, and it
sends a non-browser-like User-Agent header that risks being blocked by
NSE-family WAFs, so there's no need to run it on day one.

## Run

    python app.py

Open http://localhost:5000 — start on the Downloader page and click at least
"Last 6 Months" before checking Recommendations (short/mid/long-term need
4/11/41 trading days of history respectively; until then those horizons will
say so explicitly).

## Test

    pytest -v
