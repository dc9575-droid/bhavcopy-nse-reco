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

from flask import Flask, current_app, flash, redirect, render_template, url_for

from nse_recommender import calendar_nse, db, downloader, outcomes, recommender, status, universe


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
        finally:
            conn.close()
        return render_template("past_picks.html", picks=picks)

    return app


if __name__ == "__main__":
    flask_app = create_app()
    flask_app.run(debug=True)
