from nse_recommender.channel import STD_MULTIPLIER


def channel_svg(result, width=380, height=170, padding=20, right_padding=48):
    """A small self-contained SVG: the channel band (shaded), the fitted
    centerline (dashed), the actual close price (solid), a dot marking the
    latest close, and text labels for resistance/support/current price so
    the numbers are visible on the chart itself, not just below it. Returns
    None when the channel itself is unavailable (not enough history) so the
    caller can show a plain message instead.
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

    top_margin = 24  # room for the resistance label row
    bottom_margin = 22  # room for the support label row
    plot_top = top_margin
    plot_h = height - top_margin - bottom_margin
    # Reserve extra room on the right (beyond the last plotted point) for the
    # current-price label, which is right-anchored past the last x position --
    # without this, a label like "865.25" gets clipped by the SVG's viewBox.
    plot_w = width - padding - right_padding
    x_step = plot_w / max(n - 1, 1)

    def xy(i, value):
        x = padding + i * x_step
        y = plot_top + plot_h - (value - y_min) / y_range * plot_h
        return x, y

    def pt(i, value):
        x, y = xy(i, value)
        return f"{x:.1f},{y:.1f}"

    close_line = " ".join(pt(i, v) for i, v in enumerate(closes))
    center_line = " ".join(pt(i, v) for i, v in enumerate(fitted))
    band_polygon = " ".join(pt(i, v) for i, v in enumerate(upper)) + " " + \
        " ".join(pt(i, v) for i, v in reversed(list(enumerate(lower))))
    last_x, last_y = xy(n - 1, closes[-1])
    # Flip the current-price label above/below the dot depending on whether
    # there's room, so it never collides with the resistance label row.
    current_label_y = last_y - 10 if last_y > plot_top + 14 else last_y + 16

    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" class="channel-chart" role="img" '
        f'aria-label="Price channel chart">'
        f'<text x="{padding}" y="14" font-size="11" fill="#dc2626" font-weight="600">Resistance {result["resistance"]}</text>'
        f'<text x="{padding}" y="{height - 6}" font-size="11" fill="#16a34a" font-weight="600">Support {result["support"]}</text>'
        f'<polygon points="{band_polygon}" fill="#2563eb" fill-opacity="0.10" stroke="none" />'
        f'<polyline class="center-line" points="{center_line}" fill="none" stroke="#9ca3af" '
        f'stroke-width="1" stroke-dasharray="4,3" />'
        f'<polyline class="close-line" points="{close_line}" fill="none" stroke="#2563eb" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round" />'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3.5" fill="#2563eb" />'
        f'<text x="{last_x:.1f}" y="{current_label_y:.1f}" font-size="11" fill="#2563eb" font-weight="700" '
        f'text-anchor="end">{result["current_price"]}</text>'
        f'</svg>'
    )


def next_day_projection_svg(result, width=380, height=115, padding=44):
    """A separate, small horizontal chart: a bar spanning the one-step-ahead
    projected support-to-resistance band, a dashed tick at the projected
    centerline, and a dot for today's actual current price on that same
    scale -- with all four values labeled directly on the chart -- so it's
    visually clear whether today's price is already inside or outside where
    the trend line projects tomorrow's band to sit. This is a linear
    extrapolation of the existing trend, not a price prediction.
    """
    if not result.get("available"):
        return None

    support = result["next_support"]
    resistance = result["next_resistance"]
    centerline = result["next_centerline"]
    current = result["current_price"]

    x_min = min(support, resistance, centerline, current)
    x_max = max(support, resistance, centerline, current)
    x_range = (x_max - x_min) or 1
    plot_w = width - 2 * padding

    def x_of(value):
        return padding + (value - x_min) / x_range * plot_w

    x_support = x_of(support)
    x_resistance = x_of(resistance)
    x_centerline = x_of(centerline)
    x_current = x_of(current)
    bar_y = 40
    bar_h = 18

    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" class="channel-chart" role="img" '
        f'aria-label="Projected next-day channel">'
        f'<text x="{x_support:.1f}" y="{bar_y - bar_h / 2 - 8:.1f}" font-size="10" fill="#16a34a" '
        f'font-weight="600" text-anchor="start">S {support}</text>'
        f'<text x="{x_resistance:.1f}" y="{bar_y - bar_h / 2 - 8:.1f}" font-size="10" fill="#dc2626" '
        f'font-weight="600" text-anchor="end">R {resistance}</text>'
        f'<rect x="{x_support:.1f}" y="{bar_y - bar_h / 2:.1f}" width="{max(x_resistance - x_support, 0.1):.1f}" '
        f'height="{bar_h}" rx="4" fill="#2563eb" fill-opacity="0.12" stroke="#2563eb" stroke-width="1" />'
        f'<line x1="{x_centerline:.1f}" y1="{bar_y - bar_h / 2 - 5:.1f}" x2="{x_centerline:.1f}" '
        f'y2="{bar_y + bar_h / 2 + 5:.1f}" stroke="#9ca3af" stroke-width="1.5" stroke-dasharray="3,2" />'
        f'<text x="{x_centerline:.1f}" y="{bar_y + bar_h / 2 + 20:.1f}" font-size="10" fill="#6b7280" '
        f'text-anchor="middle">Mid {centerline}</text>'
        f'<circle cx="{x_current:.1f}" cy="{bar_y:.1f}" r="4.5" fill="#111827" />'
        f'<text x="{x_current:.1f}" y="{bar_y + bar_h / 2 + 36:.1f}" font-size="11" fill="#111827" '
        f'font-weight="700" text-anchor="middle">Now {current}</text>'
        f'</svg>'
    )
