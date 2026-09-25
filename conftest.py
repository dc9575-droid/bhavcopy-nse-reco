import pytest

from nse_recommender import news


@pytest.fixture(autouse=True)
def _block_real_news_fetch(monkeypatch):
    """No test in this suite should depend on real network access. Any code
    path that falls through to news._fetch_feed_xml (i.e. doesn't pass its
    own fetch_fn) gets a simulated outage instead of a real HTTP call.
    """
    def _raise(url):
        raise news.FeedUnavailable("real network access disabled in tests")

    monkeypatch.setattr(news, "_fetch_feed_xml", _raise)
