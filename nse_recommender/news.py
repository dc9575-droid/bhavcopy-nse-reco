import re

POSITIVE_WORDS = {
    "rally", "surge", "gain", "gains", "bullish", "upgrade",
    "growth", "boom", "recovery", "outperform",
}
NEGATIVE_WORDS = {
    "crash", "plunge", "selloff", "recession", "bearish",
    "downgrade", "default", "layoffs", "war", "slump", "slowdown",
}

MOOD_ADJUSTMENT = 0.2  # max +/-20% change to stop-loss width

_WORD_RE = re.compile(r"[a-z]+")


def _words(title):
    # Hyphens are stripped (not treated as separators) so "sell-off" reads
    # as "selloff" and still matches the single-token lexicon above.
    return set(_WORD_RE.findall(title.lower().replace("-", "")))


def score_mood(headlines):
    """Pure function, no I/O. headlines: list of {"title", "source",
    "category"}. Counts POSITIVE_WORDS/NEGATIVE_WORDS as whole-word matches
    (not substrings) across all headline titles.
    """
    if not headlines:
        return {"score": 0.0, "label": "Unavailable", "headline_count": 0}
    positive_hits = 0
    negative_hits = 0
    for h in headlines:
        words = _words(h["title"])
        positive_hits += len(words & POSITIVE_WORDS)
        negative_hits += len(words & NEGATIVE_WORDS)
    raw_score = (positive_hits - negative_hits) / len(headlines)
    score = max(-1.0, min(1.0, raw_score))
    if score >= 0.3:
        label = "Bullish"
    elif score <= -0.3:
        label = "Bearish"
    else:
        label = "Neutral"
    return {"score": round(score, 3), "label": label, "headline_count": len(headlines)}
