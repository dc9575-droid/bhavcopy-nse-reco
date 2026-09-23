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
