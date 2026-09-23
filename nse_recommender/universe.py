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
