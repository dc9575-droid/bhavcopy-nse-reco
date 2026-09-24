from datetime import date, timedelta

from nse_recommender import chart, channel
from nse_recommender.db import get_connection, init_db


def _insert_price(conn, symbol, d, close):
    conn.execute(
        "INSERT INTO bhavcopy_prices (symbol, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
        (symbol, d.isoformat(), close, close, close, close, 1000),
    )
    conn.commit()


NOISY_UPTREND = [
    100, 102, 101, 104, 103, 106, 105, 108, 107, 110,
    109, 112, 111, 114, 113, 116, 115, 118, 117, 120,
]


def _seed(conn, symbol, closes, start=date(2026, 9, 1)):
    for i, close in enumerate(closes):
        _insert_price(conn, symbol, start + timedelta(days=i), close)


def test_channel_svg_returns_none_when_channel_unavailable():
    conn = get_connection(":memory:")
    init_db(conn)
    _seed(conn, "AAA", [100, 101, 102])  # far short of the 20-day requirement
    result = channel.compute_channel(conn, "AAA")
    assert chart.channel_svg(result) is None


def test_channel_svg_renders_expected_structure():
    conn = get_connection(":memory:")
    init_db(conn)
    _seed(conn, "BBB", NOISY_UPTREND)
    result = channel.compute_channel(conn, "BBB")

    svg = chart.channel_svg(result)

    assert svg is not None
    assert svg.startswith("<svg")
    assert svg.strip().endswith("</svg>")
    assert "<polygon" in svg  # the shaded channel band
    assert "<polyline" in svg  # centerline + close price lines
    assert "<circle" in svg  # marker on the latest price

    # The close-price polyline must have exactly one point per day in the
    # 20-day window (21 numbers separated by spaces -> 20 "x,y" pairs).
    close_line_points = svg.split('class="close-line" points="')[1].split('"')[0]
    assert len(close_line_points.split(" ")) == 20


def test_channel_svg_band_is_a_uniform_parallel_strip_not_a_flared_bowtie():
    # Regression test: the polygon's lower-boundary points must keep each
    # value's ORIGINAL x-position when the list is reversed for drawing
    # (only the traversal order should reverse, not which x each y sits at).
    # A prior bug paired reversed y-values with a freshly re-enumerated index
    # (0..n-1 for the reversed list), which silently mirrored every lower
    # point's x-coordinate too, producing a flared/bowtie band shape whose
    # width varies from one end to the other instead of a constant-width
    # parallel channel.
    conn = get_connection(":memory:")
    init_db(conn)
    _seed(conn, "DDD", NOISY_UPTREND)
    result = channel.compute_channel(conn, "DDD")

    svg = chart.channel_svg(result)
    band_points_str = svg.split('<polygon points="')[1].split('"')[0]
    coords = [tuple(map(float, p.split(","))) for p in band_points_str.split(" ")]
    n = len(coords) // 2
    upper_xs = [x for x, y in coords[:n]]
    lower_xs = [x for x, y in coords[n:]]

    # The lower half is drawn right-to-left, so it must be the exact reverse
    # of the upper half's x-positions.
    assert lower_xs == list(reversed(upper_xs))

    # And therefore the vertical gap between the two boundaries (the band's
    # width) must be identical at every x -- a real parallel channel.
    upper_ys = [y for x, y in coords[:n]]
    lower_ys_by_x = dict(zip(lower_xs, [y for x, y in coords[n:]]))
    widths = [abs(lower_ys_by_x[x] - y) for x, y in zip(upper_xs, upper_ys)]
    assert max(widths) - min(widths) < 0.2  # constant, allowing for independent .1f rounding on each side


def test_channel_svg_handles_a_flat_line_without_a_zero_division_error():
    conn = get_connection(":memory:")
    init_db(conn)
    _seed(conn, "CCC", [100] * 20)  # perfectly flat: zero range, zero std
    result = channel.compute_channel(conn, "CCC")

    svg = chart.channel_svg(result)

    assert svg is not None
    assert svg.startswith("<svg")


def test_next_day_projection_svg_returns_none_when_channel_unavailable():
    conn = get_connection(":memory:")
    init_db(conn)
    _seed(conn, "EEE", [100, 101, 102])
    result = channel.compute_channel(conn, "EEE")
    assert chart.next_day_projection_svg(result) is None


def test_next_day_projection_svg_renders_band_centerline_and_current_price():
    conn = get_connection(":memory:")
    init_db(conn)
    _seed(conn, "FFF", NOISY_UPTREND)
    result = channel.compute_channel(conn, "FFF")

    svg = chart.next_day_projection_svg(result)

    assert svg is not None
    assert svg.startswith("<svg")
    assert svg.strip().endswith("</svg>")
    assert "<rect" in svg  # the projected support-to-resistance bar
    assert "<line" in svg  # the projected centerline tick
    assert "<circle" in svg  # today's current price marker on the same scale


def test_next_day_projection_svg_handles_a_flat_line_without_a_zero_division_error():
    conn = get_connection(":memory:")
    init_db(conn)
    _seed(conn, "GGG", [100] * 20)
    result = channel.compute_channel(conn, "GGG")

    svg = chart.next_day_projection_svg(result)

    assert svg is not None
    assert svg.startswith("<svg")
