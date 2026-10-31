# -*- coding: utf-8 -*-
"""Process Dashboard — Flask app phục vụ giao diện theo dõi & phân tích quy trình.

Chạy:  python app.py            (mặc định http://127.0.0.1:5000)
       python app.py --port 8000 --no-browser
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from functools import lru_cache

# Console Windows mặc định cp1252 → ép UTF-8 để in tiếng Việt
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

from flask import Flask, abort, jsonify, render_template, request

from core import analytics, models, sources

app = Flask(__name__)
app.json.ensure_ascii = False
app.config["TEMPLATES_AUTO_RELOAD"] = True


# ---------------------------------------------------------------------------
# Nạp dữ liệu (cache theo nguồn)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=8)
def get_log(source_key: str):
    loader = sources.LOADERS.get(source_key)
    if loader is None:
        return None
    return loader()


def source_or_404(source_key: str):
    try:
        log = get_log(source_key)
    except FileNotFoundError as error:
        abort(503, description=str(error))
    if log is None:
        abort(404, description=f"Nguồn dữ liệu không hợp lệ: {source_key}")
    return log


def _source_arg() -> str:
    key = request.args.get("source", "ticket")
    return key if key in sources.LOADERS else "ticket"


def _as_of_arg(log):
    return analytics.parse_as_of(log, request.args.get("as_of"))


# ---------------------------------------------------------------------------
# Định tuyến
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/sources")
def api_sources():
    items = []
    for key in sources.LOADERS:
        entry = {
            "key": key,
            "label": sources.SOURCE_LABELS[key],
            "short": sources.SOURCE_SHORT[key],
        }
        path = sources.SOURCE_PATHS[key]()
        if not path.is_file():
            entry["error"] = f"Không thấy dữ liệu: {path.name}"
        items.append(entry)
    return jsonify({"sources": items})


@app.route("/api/dashboard")
def api_dashboard():
    log = source_or_404(_source_arg())
    as_of = _as_of_arg(log)
    snap = analytics.snapshot(log, as_of)

    status = request.args.get("status", "")
    search = request.args.get("q", "")
    resource = request.args.get("resource", "")
    only_late = request.args.get("late") == "1"

    return jsonify({
        "meta": analytics.source_meta(log),
        "as_of": analytics._ts(as_of),
        "unit": log.unit,
        "overview": analytics.overview(snap),
        "process": analytics.process_view(snap),
        "resources": analytics.resources_view(snap),
        "alerts": analytics.alerts(snap),
        "cases": analytics.case_rows(snap, status=status, search=search,
                                     resource=resource, only_late=only_late),
        "activity_labels": models.ACTIVITY_LABELS,
    })


@app.route("/api/case/<path:case_id>")
def api_case(case_id: str):
    log = source_or_404(_source_arg())
    snap = analytics.snapshot(log, _as_of_arg(log))
    detail = analytics.case_detail(snap, case_id)
    if detail is None:
        abort(404, description=f"Không thấy ca {case_id} tại thời điểm này")
    return jsonify(detail)


@app.errorhandler(404)
@app.errorhandler(503)
def handle_error(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": error.description}), error.code
    return render_template("index.html"), error.code


def main() -> None:
    parser = argparse.ArgumentParser(description="Process Dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}/"
    print(f"Process Dashboard đang chạy tại {url}")
    if not args.no_browser and not args.debug:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)


if __name__ == "__main__":
    main()
