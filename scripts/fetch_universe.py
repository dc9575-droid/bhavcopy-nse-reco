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
