# -*- coding: utf-8 -*-
"""Xuất dashboard Flask thành **site tĩnh** để đăng lên GitHub Pages.

GitHub Pages chỉ phục vụ file tĩnh, nên script này "đóng băng" toàn bộ số liệu:

    docs/
    ├── index.html                 giao diện (bản tĩnh, không cần server)
    ├── static/…                   css/js/plotly (chép từ app Flask)
    └── data/
        ├── index.json             danh sách nguồn + các mốc thời gian
        └── <source>/
            ├── events.json        event log nén (để tính bảng ca phía client)
            └── p00.json … p21.json  số liệu đã tính sẵn cho từng mốc

Chạy:  python build_static.py            → xuất vào ../<repo>/docs
       python build_static.py --out DIR  → xuất vào thư mục khác
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from core import analytics, models, paths, sources

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_OUT = PROJECT_DIR.parent / "BPM-Demo" / "docs"

POINTS_PER_SOURCE = 20


# ---------------------------------------------------------------------------
# Tiện ích
# ---------------------------------------------------------------------------
def json_write(path: Path, payload) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def build_points(log, count: int = POINTS_PER_SOURCE) -> list[pd.Timestamp]:
    """Các mốc thời gian cho thanh trượt: chia đều + luôn có đỉnh tồn đọng và giữa kỳ."""
    presets = analytics.time_presets(log)
    start, end = log.min_time, log.max_time
    span = end - start
    marks = {start, end}
    for index in range(count):
        marks.add(start + span * (index / (count - 1)))
    for key in ("peak", "mid"):
        marks.add(pd.Timestamp(presets[key]))
    return sorted({mark.floor("s") for mark in marks})


def dump_events(log) -> dict:
    """Event log rút gọn: chỉ số hoá chuỗi lặp lại để file nhỏ."""
    events = log.events
    activities = list(dict.fromkeys(events["activity"].tolist()))
    resources = list(dict.fromkeys(events["resource"].tolist()))
    roles = list(dict.fromkeys(events["role"].tolist()))
    cases = list(dict.fromkeys(events["case_id"].tolist()))
    act_index = {a: i for i, a in enumerate(activities)}
    res_index = {r: i for i, r in enumerate(resources)}
    role_index = {r: i for i, r in enumerate(roles)}
    case_index = {c: i for i, c in enumerate(cases)}

    rows = []
    for row in events.itertuples():
        rows.append([
            case_index[row.case_id],
            act_index[row.activity],
            res_index[row.resource],
            role_index[row.role],
            analytics._ts(row.start_time),
            analytics._ts(row.end_time),
            None if pd.isna(row.duration) else round(float(row.duration), 4),
            None if pd.isna(row.std) else round(float(row.std), 4),
            1 if bool(row.is_late) else 0,
        ])
    return {
        "activities": activities,
        "resources": resources,
        "roles": roles,
        "cases": cases,
        "rows": rows,
    }


def source_payload(log, as_of: pd.Timestamp) -> dict:
    snap = analytics.snapshot(log, as_of)
    return {
        "as_of": analytics._ts(as_of),
        "unit": log.unit,
        "overview": analytics.overview(snap),
        "process": analytics.process_view(snap),
        "resources": analytics.resources_view(snap),
        "alerts": analytics.alerts(snap),
    }


def source_entry(log) -> dict:
    meta = analytics.source_meta(log)
    model = models.model_for(log.key)
    points = build_points(log)
    return {
        **meta,
        "terminal": list(log.terminal),
        "model": {
            "approved": bool(model.get("approved")),
            "label": model["label"],
            "arcs": [list(arc) for arc in sorted(model["arcs"])],
        },
        "points": [{"i": i, "as_of": analytics._ts(p)} for i, p in enumerate(points)],
        "norms": {k: round(float(v), 4) for k, v in log.meta.get("norms", {}).items()},
        "events": f"data/{log.key}/events.json",
        "payload": f"data/{log.key}/p00.json",
        "_timestamps": points,
    }


# ---------------------------------------------------------------------------
# Dựng site
# ---------------------------------------------------------------------------
def copy_assets(out: Path) -> None:
    vendor = PROJECT_DIR / "static" / "vendor" / "plotly.min.js"
    if not vendor.is_file():
        # Trong repo, file vendor được bỏ qua khi clone → lấy lại từ gói plotly đã cài
        try:
            import plotly
            source = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
            vendor.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, vendor)
            print("  · đã phục hồi static/vendor/plotly.min.js từ gói plotly")
        except Exception as error:  # pragma: no cover
            raise SystemExit(
                "Thiếu static/vendor/plotly.min.js và không lấy được từ gói plotly. "
                f"Chạy: pip install plotly  (lỗi: {error})")

    static_src = PROJECT_DIR / "static"
    static_dst = out / "static"
    if static_dst.exists():
        shutil.rmtree(static_dst)
    shutil.copytree(static_src, static_dst, ignore=shutil.ignore_patterns("__pycache__"))

    template = (PROJECT_DIR / "templates" / "index.html").read_text(encoding="utf-8")
    template = (template
                .replace("{{ url_for('static', filename='css/app.css') }}", "static/css/app.css")
                .replace("{{ url_for('static', filename='vendor/plotly.min.js') }}", "static/vendor/plotly.min.js")
                .replace("{{ url_for('static', filename='js/app.js') }}", "static/js/app.js"))
    template = template.replace(
        '<script src="static/js/app.js"></script>',
        '<script>window.__STATIC__ = true;</script>\n<script src="static/js/app.js"></script>',
    )
    (out / "index.html").write_text(template, encoding="utf-8")


def build(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    copy_assets(out)

    entries = []
    total = 0
    for key, loader in sources.LOADERS.items():
        log = loader()
        entry = source_entry(log)
        timestamps = entry.pop("_timestamps")
        entries.append(entry)

        events_size = json_write(out / entry["events"], dump_events(log))
        total += events_size

        payload_sizes = 0
        for i, moment in enumerate(timestamps):
            payload_sizes += json_write(out / f"data/{key}/p{i:02d}.json", source_payload(log, moment))

        print(f"  {key:11} {len(timestamps):>2} mốc · events {events_size/1024:6.0f} KB · "
              f"payload {payload_sizes/1024:6.0f} KB · {entry['n_cases']:>5} ca")
        total += payload_sizes

    index = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "activity_labels": models.ACTIVITY_LABELS,
        "sources": entries,
    }
    total += json_write(out / "data" / "index.json", index)
    print(f"  Tổng dữ liệu: {total/1024/1024:.2f} MB → {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Xuất dashboard thành site tĩnh")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"thư mục đích (mặc định: {DEFAULT_OUT})")
    args = parser.parse_args()
    target = args.out.resolve()
    print(f"Đang xuất site tĩnh vào {target}")
    build(target)
    print("Xong. Mở bằng:  python -m http.server 8080 --directory", target)


if __name__ == "__main__":
    main()
