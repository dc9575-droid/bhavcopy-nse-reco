from nse_recommender import news


def test_score_mood_with_no_headlines_is_unavailable():
    result = news.score_mood([])
    assert result == {"score": 0.0, "label": "Unavailable", "headline_count": 0}


def test_score_mood_clearly_bullish_headlines():
    headlines = [
        {"title": "Sensex, Nifty rally as global cues turn positive", "source": "ET", "category": "national"},
        {"title": "Markets surge on strong earnings", "source": "ET", "category": "national"},
        {"title": "IT stocks see broad-based gains", "source": "BS", "category": "national"},
    ]
    result = news.score_mood(headlines)
    # 3 positive hits ("rally", "surge", "gains"), 0 negative, over 3 headlines -> 1.0
    assert result["score"] == 1.0
    assert result["label"] == "Bullish"
    assert result["headline_count"] == 3


def test_score_mood_clearly_bearish_headlines():
    headlines = [
        {"title": "Markets crash amid recession fears", "source": "ET", "category": "national"},
        {"title": "Selloff deepens as bearish sentiment grows", "source": "BS", "category": "national"},
        {"title": "Global slowdown fears trigger declines", "source": "BBC", "category": "international"},
    ]
    result = news.score_mood(headlines)
    # negative hits: crash+recession=2, selloff+bearish=2, slowdown=1 -> 5 over 3
    # headlines -> raw -1.667, clamped to -1.0
    assert result["score"] == -1.0
    assert result["label"] == "Bearish"


def test_score_mood_mixed_headlines_is_neutral():
    headlines = [
        {"title": "Sensex ends flat in a quiet session", "source": "ET", "category": "national"},
        {"title": "IT stocks gain while banks slip", "source": "BS", "category": "national"},
        {"title": "Auto sector faces mixed trade amid crash in commodity prices", "source": "BBC", "category": "international"},
    ]
    result = news.score_mood(headlines)
    # 1 positive ("gain"), 1 negative ("crash") over 3 headlines -> 0.0
    assert result["score"] == 0.0
    assert result["label"] == "Neutral"


def test_score_mood_matches_hyphenated_negative_words():
    # "Sell-off" must match the same as "selloff" -- hyphens are stripped
    # before word-matching so headline styling doesn't cause a miss.
    headlines = [{"title": "Global sell-off wipes out gains", "source": "BBC", "category": "international"}]
    result = news.score_mood(headlines)
    # "selloff" (negative) + "gains" (positive) -> net 0 over 1 headline
    assert result["score"] == 0.0


def test_score_mood_does_not_match_lexicon_words_as_substrings():
    # "boombox" contains "boom" as a substring but is not the word "boom" --
    # whole-word matching must not count it. Naive substring matching would
    # incorrectly score this as positive.
    headlines = [{"title": "New boombox launches at retail stores", "source": "BBC", "category": "international"}]
    result = news.score_mood(headlines)
    assert result["score"] == 0.0
    assert result["label"] == "Neutral"
