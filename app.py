import os

# Must run before pandas/numpy are imported (via nse_recommender.recommender below):
# on shared hosting with a low per-account process/thread limit, numpy's bundled
# OpenBLAS spawning one thread per CPU core at import time can exceed the limit
# and segfault. Forcing single-threaded BLAS avoids it; harmless everywhere else.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

from datetime import date

from flask import Flask, current_app, flash, redirect, render_template, request, url_for

from nse_recommender import calendar_nse, chart, channel, db, downloader, outcomes, recommender, status, streaks, universe


def create_app(db_path=None, symbols=None):
    app = Flask(__name__)
    app.secret_key = "nse-recommender-v1"
    resolved_db_path = db_path if db_path is not None else db.DB_PATH
    conn = db.get_connection(resolved_db_path)
    db.init_db(conn)
    conn.close()
    app.config["DB_PATH"] = resolved_db_path
    app.config["SYMBOLS"] = symbols if symbols is not None else universe.load_nifty500_symbols()

    @app.route("/")
    def index():
        conn = db.get_connection(current_app.config["DB_PATH"])
        try:
            coverage = status.coverage_summary(conn, date.today())
        finally:
            conn.close()
        return render_template("index.html", coverage=coverage)

    @app.route("/download/<label>", methods=["POST"])
    def download(label):
        conn = db.get_connection(current_app.config["DB_PATH"])
        try:
            dates = calendar_nse.range_for_label(label, date.today())
            results = downloader.download_missing_days(conn, dates, set(current_app.config["SYMBOLS"]))
        finally:
            conn.close()
        flash(
            f"{len(results['success'])} downloaded, "
            f"{len(results['no_data'])} no data, "
            f"{len(results['failed'])} failed"
        )
        return redirect(url_for("index"))

    @app.route("/recommendations")
    def recommendations():
        conn = db.get_connection(current_app.config["DB_PATH"])
        try:
            generated_date = date.today().isoformat()
            results = recommender.generate_and_save_all(
                conn, current_app.config["SYMBOLS"], generated_date
            )
        finally:
            conn.close()
        return render_template("recommendations.html", results=results, generated_date=generated_date)

    @app.route("/past-picks")
    def past_picks():
        conn = db.get_connection(current_app.config["DB_PATH"])
        try:
            picks = outcomes.list_past_picks(conn)
            daily = outcomes.daily_results(conn)
        finally:
            conn.close()

        filter_horizon = request.args.get("horizon") or None
        filter_period = request.args.get("period") or None
        filter_status = request.args.get("status") or None
        filter_active = bool(filter_horizon or filter_period or filter_status)
        filtered_picks = outcomes.filter_picks(
            picks, horizon=filter_horizon, period=filter_period, status=filter_status
        )

        return render_template(
            "past_picks.html",
            picks=filtered_picks,
            all_picks_count=len(picks),
            daily=daily,
            filter_active=filter_active,
            filter_horizon=filter_horizon,
            filter_period=filter_period,
            filter_status=filter_status,
        )

    @app.route("/stock")
    def stock():
        symbol = request.args.get("symbol", "").strip().upper()
        result = None
        if symbol:
            conn = db.get_connection(current_app.config["DB_PATH"])
            try:
                streak = streaks.current_streak(conn, symbol)
                chan = channel.compute_channel(conn, symbol)
                horizons = {
                    horizon_key: recommender.symbol_momentum(conn, symbol, horizon_key)
                    for horizon_key in recommender.HORIZONS
                }
            finally:
                conn.close()
            result = {
                "in_universe": symbol in current_app.config["SYMBOLS"],
                "has_data": streak["current_price"] is not None,
                "streak": streak,
                "channel": chan,
                "chart_svg": chart.channel_svg(chan),
                "next_chart_svg": chart.next_day_projection_svg(chan),
                "horizons": horizons,
            }
        return render_template("stock.html", symbol=symbol, result=result)

    return app


if __name__ == "__main__":
    flask_app = create_app()
    # host="0.0.0.0" binds all network interfaces (not just 127.0.0.1), so the
    # app is also reachable via a LAN or Tailscale IP, e.g. http://<tailscale-ip>:5000/
    flask_app.run(host="0.0.0.0", debug=True)
