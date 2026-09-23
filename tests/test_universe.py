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
