from nse_recommender.channel import STD_MULTIPLIER


def channel_svg(result, width=380, height=160, padding=20):
    """A small self-contained SVG: the channel band (shaded), the fitted
    centerline (dashed), the actual close price (solid), and a dot marking
    the latest close. Returns None when the channel itself is unavailable
    (not enough history) so the caller can show a plain message instead.
    """
    if not result.get("available"):
        return None

    points = result["points"]
    resid_std = result["resid_std"]
    n = len(points)
    closes = [p["close"] for p in points]
    fitted = [p["fitted"] for p in points]
    upper = [f + STD_MULTIPLIER * resid_std for f in fitted]
    lower = [f - STD_MULTIPLIER * resid_std for f in fitted]

    y_min = min(closes + upper + lower)
    y_max = max(closes + upper + lower)
    y_range = (y_max - y_min) or 1  # a perfectly flat series has zero range

    plot_w = width - 2 * padding
    plot_h = height - 2 * padding
    x_step = plot_w / max(n - 1, 1)

    def xy(i, value):
        x = padding + i * x_step
        y = padding + plot_h - (value - y_min) / y_range * plot_h
        return f"{x:.1f},{y:.1f}"

    close_line = " ".join(xy(i, v) for i, v in enumerate(closes))
    center_line = " ".join(xy(i, v) for i, v in enumerate(fitted))
    band_polygon = " ".join(xy(i, v) for i, v in enumerate(upper)) + " " + \
        " ".join(xy(i, v) for i, v in reversed(list(enumerate(lower))))
    last_x, last_y = xy(n - 1, closes[-1]).split(",")

    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Price channel chart">'
        f'<polygon points="{band_polygon}" fill="#2563eb" fill-opacity="0.10" stroke="none" />'
        f'<polyline class="center-line" points="{center_line}" fill="none" stroke="#9ca3af" '
        f'stroke-width="1" stroke-dasharray="4,3" />'
        f'<polyline class="close-line" points="{close_line}" fill="none" stroke="#2563eb" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round" />'
        f'<circle cx="{last_x}" cy="{last_y}" r="3.5" fill="#2563eb" />'
        f'</svg>'
    )
