# -*- coding: utf-8 -*-
"""Tính toán cho dashboard: KPI, bảng ca, DFG, biến thể, tuân thủ, cảnh báo.

Mọi hàm nhận vào một ``Snapshot`` = (event log, thời điểm quan sát) để dashboard
có thể "tua" thời gian và xem quy trình đúng như nó đang diễn ra tại thời điểm đó.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass

import networkx as nx
import numpy as np
import pandas as pd

from . import models
from .sources import DAYS, SOURCE_SHORT, EventLog, MINUTES, WORKDAYS, elapsed

COMPLETED = "Hoàn thành"
REJECTED = "Bị từ chối"
OPEN = "Đang mở"


# ---------------------------------------------------------------------------
# Tiện ích
# ---------------------------------------------------------------------------
def _ts(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%dT%H:%M:%S")


def _num(value, nd: int = 2):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, nd)


def _pct(part, whole) -> float:
    return round(100.0 * float(part) / float(whole), 1) if whole else 0.0


def _vn(value, nd: int = 1) -> str:
    """Số kiểu Việt Nam: 12,5 thay cho 12.5."""
    try:
        text = f"{float(value):.{nd}f}"
    except (TypeError, ValueError):
        return "—"
    text = text.rstrip("0").rstrip(".")
    return (text or "0").replace(".", ",")


def parse_as_of(log: EventLog, raw: str | None) -> pd.Timestamp:
    if not raw:
        return log.max_time
    try:
        stamp = pd.Timestamp(raw)
    except (ValueError, TypeError):
        return log.max_time
    if stamp.tzinfo is not None:
        stamp = stamp.tz_localize(None)
    return min(max(stamp, log.min_time), log.max_time)


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------
@dataclass
class Snapshot:
    log: EventLog
    as_of: pd.Timestamp
    events: pd.DataFrame
    cases: pd.DataFrame
    activity_order: dict[str, float]
    norms: dict[str, float]

    @property
    def unit(self) -> str:
        return self.log.unit


def _clip_to_as_of(events: pd.DataFrame, log: EventLog, as_of: pd.Timestamp) -> pd.DataFrame:
    """Bước đang diễn ra tại `as_of` chỉ được tính tới thời điểm quan sát.

    Nếu không cắt, ca còn mở sẽ mang thời lượng *tương lai* (đã ghi trong log gốc),
    khiến KPI của quá khứ bị rò rỉ thông tin về tương lai.
    """
    if events.empty:
        return events
    tail = events.groupby("case_id", sort=False).tail(1)
    open_tail = tail[~tail["activity"].isin(log.terminal)]
    for index, row in open_tail.iterrows():
        dwell = elapsed(row["start_time"], as_of, log.unit_key)
        std = row["std"]
        has_std = std is not None and not pd.isna(std)
        events.at[index, "duration"] = dwell
        events.at[index, "end_time"] = pd.NaT
        events.at[index, "is_late"] = bool(has_std and dwell > float(std))
        events.at[index, "delay"] = max(0.0, dwell - (float(std) if has_std else 0.0))
    return events


def build_snapshot(log: EventLog, as_of: pd.Timestamp | None = None) -> Snapshot:
    as_of = as_of if as_of is not None else log.max_time
    events = log.events[log.events["start_time"] <= as_of].copy()
    if events.empty:
        events = log.events.head(1).copy()
    events = _clip_to_as_of(events, log, as_of)

    norms = dict(log.meta.get("norms", {}))
    grouped = events.groupby("case_id", sort=True)

    tail = grouped.tail(1).set_index("case_id")
    agg = grouped.agg(
        n_events=("activity", "size"),
        n_late=("is_late", "sum"),
        delay_total=("delay", "sum"),
        n_distinct=("activity", "nunique"),
        first_start=("start_time", "min"),
        last_start=("start_time", "max"),
    )

    cases = agg.copy()
    cases["variant"] = grouped["activity"].agg(lambda s: " → ".join(s))
    cases["resources"] = grouped["resource"].agg(lambda s: " · ".join(dict.fromkeys(s)))
    cases["resource"] = grouped["resource"].first()
    cases["role"] = grouped["role"].first()
    cases["last_activity"] = tail["activity"]
    cases["last_end"] = tail["end_time"]
    cases["rework"] = cases["n_events"] - cases["n_distinct"]
    cases["late_share"] = (100.0 * cases["n_late"] / cases["n_events"]).round(1)

    activity = cases["last_activity"].astype(str)
    is_terminal = activity.isin(log.terminal)
    is_rejected = activity.str.lower().str.startswith("từ chối") | (activity == "Rejected")
    cases["status"] = np.where(is_terminal, np.where(is_rejected, REJECTED, COMPLETED), OPEN)
    cases["is_open"] = cases["status"] == OPEN

    factor = 60.0 if log.unit_key == MINUTES else 86_400.0
    finish = cases["last_end"].fillna(cases["last_start"]).where(~cases["is_open"], as_of)
    if log.unit_key == WORKDAYS:
        cases["cycle"] = [elapsed(a, b, log.unit_key)
                          for a, b in zip(cases["first_start"], finish)]
    else:
        cases["cycle"] = (finish - cases["first_start"]).dt.total_seconds() / factor

    std_last = cases["last_activity"].map(norms)
    cases["std_last"] = std_last

    if log.unit_key == WORKDAYS:
        dwell = np.zeros(len(cases))
        for position, (start, is_open) in enumerate(zip(cases["last_start"], cases["is_open"])):
            if is_open:
                dwell[position] = elapsed(start, as_of, log.unit_key)
        dwell = pd.Series(dwell, index=cases.index)
    else:
        elapsed_now = (as_of - cases["last_start"]).dt.total_seconds() / factor
        dwell = pd.Series(np.where(cases["is_open"], elapsed_now, 0.0), index=cases.index)

    # ca đã đóng: bước cuối không phải trạng thái kết thúc → dùng thời lượng bước cuối
    tail_duration = tail["duration"].reindex(cases.index)
    closed_extra = (~cases["is_open"]) & (~activity.isin(("DONE", "Rejected")))
    if bool(closed_extra.any()):
        dwell = dwell.where(~closed_extra, tail_duration.fillna(0.0))
    cases["dwell"] = dwell

    cases["overdue_now"] = cases["is_open"] & std_last.notna() & (dwell > std_last.fillna(0.0))
    cases["on_time"] = cases["n_late"] <= 0
    cases = cases.reset_index()

    # vị trí trung bình của mỗi hoạt động trong ca → dùng để xếp hạng đồ thị
    positions = events[["case_id", "activity"]].copy()
    positions["pos"] = positions.groupby("case_id").cumcount()
    size = positions.groupby("case_id")["activity"].transform("size")
    positions["rel"] = positions["pos"] / (size - 1).clip(lower=1)
    activity_order = positions.groupby("activity")["rel"].mean().to_dict()
    activity_order = {k: round(float(v), 4) for k, v in activity_order.items()}

    return Snapshot(log=log, as_of=as_of, events=events, cases=cases,
                    activity_order=activity_order, norms=norms)


_SNAPSHOTS: "OrderedDict[tuple[str, str], Snapshot]" = OrderedDict()
_SNAPSHOT_CACHE_SIZE = 24
# Trần số sự kiện giữ trong cache: bộ Helpdesk (21k sự kiện/snapshot) chỉ giữ ~7 mốc
_CACHE_EVENT_BUDGET = 150_000
_PRESETS: dict[str, dict] = {}


def snapshot(log: EventLog, as_of: pd.Timestamp | None = None) -> Snapshot:
    """`build_snapshot` có cache — tua thanh thời gian qua lại vẫn nhanh."""
    as_of = as_of if as_of is not None else log.max_time
    key = (log.key, pd.Timestamp(as_of).isoformat())
    if key in _SNAPSHOTS:
        _SNAPSHOTS.move_to_end(key)
        return _SNAPSHOTS[key]

    built = build_snapshot(log, as_of)
    _SNAPSHOTS[key] = built
    cached_events = sum(len(s.events) for s in _SNAPSHOTS.values())
    while len(_SNAPSHOTS) > 1 and (len(_SNAPSHOTS) > _SNAPSHOT_CACHE_SIZE
                                   or cached_events > _CACHE_EVENT_BUDGET):
        _, dropped = _SNAPSHOTS.popitem(last=False)
        cached_events -= len(dropped.events)
    return built


# ---------------------------------------------------------------------------
# Mốc thời gian gợi ý (cao điểm tồn đọng, giữa kỳ)
# ---------------------------------------------------------------------------
def time_presets(log: EventLog) -> dict:
    cached = _PRESETS.get(log.key)
    if cached is not None:
        return dict(cached)

    events = log.events.sort_values("start_time")
    tail = events.groupby("case_id").tail(1).set_index("case_id")
    close = tail["end_time"].fillna(tail["start_time"]).astype("datetime64[ns]")
    closed = tail["activity"].isin(log.terminal)

    starts = events.groupby("case_id")["start_time"].min()
    marks: list[tuple[pd.Timestamp, int]] = []
    for case_id, start in starts.items():
        marks.append((pd.Timestamp(start), +1))
        if bool(closed.get(case_id, False)):
            marks.append((pd.Timestamp(close.get(case_id)), -1))
    marks.sort()

    running = 0
    best = (-1, log.min_time)
    for stamp, delta in marks:
        running += delta
        if delta > 0 and running > best[0]:
            best = (running, stamp)

    span = log.max_time - log.min_time
    presets = {
        "start": _ts(log.min_time),
        "end": _ts(log.max_time),
        "peak": _ts(best[1]),
        "peak_open": int(max(best[0], 0)),
        "mid": _ts(log.min_time + span * 0.6),
    }
    _PRESETS[log.key] = presets
    return dict(presets)


# ---------------------------------------------------------------------------
# Tổng quan
# ---------------------------------------------------------------------------
def overview(snap: Snapshot) -> dict:
    events, cases = snap.events, snap.cases
    unit = snap.unit
    finished = cases[cases["status"] != OPEN]
    open_cases = cases[cases["status"] == OPEN]
    n_late = int(events["is_late"].sum())

    cycle_values = finished["cycle"].tolist() if len(finished) else []
    median_cycle = float(np.median(cycle_values)) if cycle_values else 0.0
    p90_cycle = float(np.percentile(cycle_values, 90)) if cycle_values else 0.0

    kpi = [
        {"key": "cases", "label": "Số ca", "value": len(cases), "unit": "ca",
         "hint": "Số case trong phạm vi dữ liệu", "tone": "blue"},
        {"key": "events", "label": "Số sự kiện", "value": len(events), "unit": "bước",
         "hint": "Tổng số bước đã ghi nhận", "tone": "slate"},
        {"key": "on_time", "label": "Đúng hạn", "value": _pct(len(events) - n_late, len(events)),
         "unit": "%", "hint": f"{len(events) - n_late}/{len(events)} bước đạt định mức", "tone": "green"},
        {"key": "late", "label": "Quá hạn", "value": _pct(n_late, len(events)),
         "unit": "%", "hint": f"{n_late} bước vượt định mức", "tone": "red"},
        {"key": "median_cycle", "label": "Chu kỳ trung vị", "value": _num(median_cycle, 1),
         "unit": unit, "hint": "Thời gian từ bước đầu đến khi kết thúc", "tone": "violet"},
        {"key": "p90_cycle", "label": "Chu kỳ P90", "value": _num(p90_cycle, 1),
         "unit": unit, "hint": "90% ca hoàn thành nhanh hơn mức này", "tone": "amber"},
        {"key": "open", "label": "Đang mở", "value": len(open_cases), "unit": "ca",
         "hint": "Ca chưa tới bước kết thúc tại thời điểm quan sát", "tone": "cyan"},
        {"key": "overdue_now", "label": "Trễ hạn hiện tại", "value": int(open_cases["overdue_now"].sum()),
         "unit": "ca", "hint": "Ca đang mở và đã vượt định mức ở bước hiện tại", "tone": "red"},
    ]

    # số sự kiện / ca bắt đầu / ca kết thúc theo thời gian (tự chọn độ phân giải)
    ev = events.copy()
    ev["day"] = ev["start_time"].dt.normalize()
    spans = int((ev["day"].max() - ev["day"].min()).days) if len(ev) else 0
    if spans <= 31:
        freq, tickformat, gran_label = "D", "%d/%m", "ngày"
    elif spans <= 200:
        freq, tickformat, gran_label = "W-MON", "%d/%m", "tuần"
    else:
        freq, tickformat, gran_label = "MS", "%m/%Y", "tháng"

    per_day = ev.set_index("day").resample(freq).size()
    start_days = events.groupby("case_id")["start_time"].min().dt.normalize()
    end_days = finished.set_index("case_id")["last_start"].dt.normalize() if len(finished) else pd.Series(dtype="datetime64[ns]")
    started = start_days.value_counts().sort_index().resample(freq).sum().reindex(per_day.index, fill_value=0)
    ended = (end_days.value_counts().sort_index().resample(freq).sum().reindex(per_day.index, fill_value=0)
             if len(end_days) else pd.Series(0, index=per_day.index))
    daily = {
        "dates": [d.strftime("%Y-%m-%d") for d in per_day.index],
        "events": [int(v) for v in per_day.values],
        "started": [int(v) for v in started.values],
        "finished": [int(v) for v in ended.values],
        "granularity": gran_label,
        "tickformat": tickformat,
    }

    # phân bố chu kỳ
    if cycle_values:
        counts, edges = np.histogram(cycle_values, bins=min(20, max(5, len(cycle_values) // 3)))
        centers = [round(float((edges[i] + edges[i + 1]) / 2), 2) for i in range(len(counts))]
        cycle_hist = {"x": centers, "y": [int(c) for c in counts]}
    else:
        cycle_hist = {"x": [], "y": []}

    # theo hoạt động
    act = (events.groupby("activity")
           .agg(visits=("case_id", "size"),
                avg_duration=("duration", "mean"),
                std=("std", "mean"),
                late=("is_late", "sum"),
                delay=("delay", "sum"))
           .reset_index())
    act["on_time_pct"] = act.apply(lambda r: _pct(r["visits"] - r["late"], r["visits"]), axis=1)
    act["late_pct"] = act.apply(lambda r: _pct(r["late"], r["visits"]), axis=1)
    act = act.sort_values(["late_pct", "visits"], ascending=[False, False])
    activity_rows = [{
        "activity": r["activity"],
        "visits": int(r["visits"]),
        "avg_duration": _num(r["avg_duration"], 2),
        "std": _num(r["std"], 2),
        "late": int(r["late"]),
        "on_time_pct": r["on_time_pct"],
        "late_pct": r["late_pct"],
        "delay": _num(r["delay"], 1),
    } for _, r in act.iterrows()]

    # cơ cấu trạng thái ca
    status_counts = cases["status"].value_counts()
    status_mix = {
        "labels": status_counts.index.tolist(),
        "values": [int(v) for v in status_counts.values],
    }

    # phân bố ca theo người xử lý
    by_resource = (events.groupby("resource")
                   .agg(events=("case_id", "size"), cases=("case_id", "nunique"),
                        late=("is_late", "sum"), avg=("duration", "mean"))
                   .reset_index()
                   .sort_values("events", ascending=False))
    resource_mix = [{
        "resource": r["resource"],
        "events": int(r["events"]),
        "cases": int(r["cases"]),
        "on_time_pct": _pct(r["events"] - r["late"], r["events"]),
        "avg_duration": _num(r["avg"], 2),
    } for _, r in by_resource.iterrows()]

    return {
        "as_of": _ts(snap.as_of),
        "unit": unit,
        "kpi": kpi,
        "daily": daily,
        "cycle_hist": cycle_hist,
        "activity_rows": activity_rows,
        "status_mix": status_mix,
        "resource_mix": resource_mix,
        "rework_cases": int((cases["rework"] > 0).sum()),
    }


# ---------------------------------------------------------------------------
# Bảng ca (theo dõi vận hành)
# ---------------------------------------------------------------------------
def case_rows(snap: Snapshot, status: str = "", search: str = "",
              resource: str = "", only_late: bool = False) -> list[dict]:
    cases = snap.cases
    if status:
        cases = cases[cases["status"] == status]
    if resource:
        cases = cases[cases["resources"].str.contains(resource, na=False, regex=False)]
    if only_late:
        cases = cases[(cases["n_late"] > 0) | (cases["overdue_now"])]
    if search:
        needle = search.strip().lower()
        cases = cases[cases["case_id"].astype(str).str.lower().str.contains(needle, na=False, regex=False)]

    rows = []
    for r in cases.itertuples():
        rows.append({
            "case_id": r.case_id,
            "status": r.status,
            "is_open": bool(r.is_open),
            "last_activity": r.last_activity,
            "last_start": _ts(r.last_start),
            "dwell": _num(r.dwell, 2),
            "std_last": _num(r.std_last, 2),
            "overdue_now": bool(r.overdue_now),
            "cycle": _num(r.cycle, 2),
            "n_events": int(r.n_events),
            "n_late": int(r.n_late),
            "late_share": _num(r.late_share, 1),
            "delay_total": _num(r.delay_total, 1),
            "resource": r.resource,
            "resources": r.resources,
            "role": r.role,
            "rework": int(r.rework),
        })
    rows.sort(key=lambda x: x["last_start"] or "", reverse=True)
    rows.sort(key=lambda x: x["status"] != OPEN)
    return rows


def case_detail(snap: Snapshot, case_id: str) -> dict | None:
    events = snap.events
    group = events[events["case_id"] == case_id].sort_values("start_time")
    if group.empty:
        return None
    case = snap.cases[snap.cases["case_id"] == case_id]
    case = case.iloc[0].to_dict() if len(case) else {}

    timeline = []
    for index, r in enumerate(group.itertuples()):
        duration = None if pd.isna(r.duration) else float(r.duration)
        std = None if pd.isna(r.std) else float(r.std)
        timeline.append({
            "index": index + 1,
            "activity": r.activity,
            "resource": r.resource,
            "role": r.role,
            "start": _ts(r.start_time),
            "end": _ts(r.end_time),
            "duration": _num(duration, 2),
            "std": _num(std, 2),
            "is_late": bool(r.is_late),
            "delay": _num(r.delay, 2),
            "note": r.note or "",
        })

    model = models.model_for(snap.log.key)
    arcs = model["arcs"]
    approved = bool(model.get("approved"))
    steps = []
    for prev, cur in zip(timeline, timeline[1:]):
        steps.append({
            "from": prev["activity"], "to": cur["activity"],
            "in_model": (prev["activity"], cur["activity"]) in arcs if approved else None,
        })

    return {
        "case_id": case_id,
        "status": case.get("status"),
        "variant": case.get("variant"),
        "cycle": _num(case.get("cycle"), 2),
        "unit": snap.unit,
        "as_of": _ts(snap.as_of),
        "start": _ts(group["start_time"].iloc[0]),
        "end": _ts(group["end_time"].dropna().iloc[-1]) if group["end_time"].notna().any() else None,
        "timeline": timeline,
        "transitions": steps,
        "deviations": [s for s in steps if s["in_model"] is False],
        "model_approved": approved,
    }


# ---------------------------------------------------------------------------
# Phân tích quy trình
# ---------------------------------------------------------------------------
def _directly_follows(events: pd.DataFrame) -> pd.DataFrame:
    frame = events[["case_id", "activity", "is_late", "duration"]].copy()
    frame["source"] = frame.groupby("case_id")["activity"].shift(1)
    frame = frame[frame["source"].notna()]
    return pd.DataFrame({
        "case_id": frame["case_id"],
        "source": frame["source"],
        "target": frame["activity"],
        "target_late": frame["is_late"],
        "target_duration": frame["duration"],
    })


def process_view(snap: Snapshot) -> dict:
    events = snap.events
    order = snap.activity_order

    node_stats = (events.groupby("activity")
                  .agg(visits=("case_id", "size"),
                       late=("is_late", "sum"),
                       avg_duration=("duration", "mean"),
                       role=("role", lambda s: s.mode().iat[0] if len(s.mode()) else "unknown"))
                  .reset_index())
    nodes = []
    for _, r in node_stats.iterrows():
        nodes.append({
            "id": r["activity"],
            "label": r["activity"],
            "visits": int(r["visits"]),
            "on_time_pct": _pct(r["visits"] - r["late"], r["visits"]),
            "avg_duration": _num(r["avg_duration"], 2),
            "role": r["role"],
            "order": round(order.get(r["activity"], 0.5), 3),
        })
    nodes.sort(key=lambda n: n["order"])
    index_of = {n["id"]: i for i, n in enumerate(nodes)}

    dfg = _directly_follows(events)
    model = models.model_for(snap.log.key)
    links, edges = [], []
    if not dfg.empty:
        agg = (dfg.groupby(["source", "target"])
               .agg(count=("case_id", "size"), late=("target_late", "sum"),
                    duration=("target_duration", "mean"))
               .reset_index()
               .sort_values("count", ascending=False))
        total = int(agg["count"].sum())
        approved = bool(model.get("approved"))
        for _, r in agg.iterrows():
            if r["source"] not in index_of or r["target"] not in index_of:
                continue
            in_model = (r["source"], r["target"]) in model["arcs"] if approved else True
            links.append({
                "source": index_of[r["source"]],
                "target": index_of[r["target"]],
                "value": int(r["count"]),
                "in_model": in_model,
            })
            edges.append({
                "source": r["source"],
                "target": r["target"],
                "count": int(r["count"]),
                "share": _pct(r["count"], total),
                "avg_duration": _num(r["duration"], 2),
                "in_model": in_model,
            })

    # biến thể
    variants = (snap.cases.groupby("variant")
                .agg(count=("case_id", "size"),
                     avg_cycle=("cycle", "mean"),
                     late=("n_late", "sum"),
                     steps=("n_events", "mean"))
                .reset_index()
                .sort_values("count", ascending=False))
    total_cases = int(variants["count"].sum())
    variant_rows = []
    for _, r in variants.head(15).iterrows():
        steps = r["variant"].split(" → ")
        variant_rows.append({
            "variant": r["variant"],
            "short": " → ".join(steps[:8]) + (" …" if len(steps) > 8 else ""),
            "steps": len(steps),
            "count": int(r["count"]),
            "share": _pct(r["count"], total_cases),
            "avg_cycle": _num(r["avg_cycle"], 2),
            "avg_steps": _num(r["steps"], 1),
        })

    # tuân thủ mô hình chuẩn
    approved = bool(model.get("approved"))
    total_transitions = int(len(dfg))
    in_model = 0
    trace_fit = 0.0
    covered_arcs = 0
    if not dfg.empty and approved:
        arcs = model["arcs"]
        dfg["in_model"] = [(s, t) in arcs for s, t in zip(dfg["source"], dfg["target"])]
        in_model = int(dfg["in_model"].sum())
        per_case = dfg.groupby("case_id")["in_model"].all()
        n_cases = max(int(snap.cases.shape[0]), 1)
        # ca chỉ có 1 bước → không có cạnh nào → coi là khớp
        single_step = n_cases - int(len(per_case))
        trace_fit = _pct(int(per_case.sum()) + single_step, n_cases)
        covered_arcs = len({(s, t) for s, t in zip(dfg["source"], dfg["target"])} & arcs)
    deviation_edges = [e for e in edges if not e["in_model"]]
    deviation_edges.sort(key=lambda e: -e["count"])

    covered = set(events["activity"].unique())
    missing_nodes = sorted(model["reachable_nodes"] - covered) if approved else []
    model_arcs_total = len(model["arcs"]) if approved else 0

    return {
        "nodes": nodes,
        "links": links,
        "edges": edges,
        "variants": variant_rows,
        "variant_total": total_cases,
        "conformance": {
            "approved": approved,
            "fit_pct": _pct(in_model, total_transitions) if approved else None,
            "in_model": in_model,
            "transitions": total_transitions,
            "deviations": deviation_edges[:12],
            "model_label": model["label"],
            "model_arcs_total": model_arcs_total,
            "model_arcs_covered": covered_arcs,
            "coverage_pct": _pct(covered_arcs, model_arcs_total) if approved else None,
            "missing_nodes": missing_nodes,
            "trace_fit_pct": trace_fit if approved else None,
        },
        "unit": snap.unit,
    }


# ---------------------------------------------------------------------------
# Nguồn lực & bàn giao
# ---------------------------------------------------------------------------
def resources_view(snap: Snapshot) -> dict:
    events = snap.events

    stats = (events.groupby(["resource", "role"])
             .agg(events=("case_id", "size"),
                  cases=("case_id", "nunique"),
                  late=("is_late", "sum"),
                  avg=("duration", "mean"),
                  delay=("delay", "sum"))
             .reset_index())
    nodes = [{
        "resource": r["resource"],
        "role": r["role"],
        "events": int(r["events"]),
        "cases": int(r["cases"]),
        "on_time_pct": _pct(r["events"] - r["late"], r["events"]),
        "avg_duration": _num(r["avg"], 2),
        "delay": _num(r["delay"], 1),
    } for _, r in stats.iterrows()]
    nodes.sort(key=lambda n: -n["events"])

    # mạng bàn giao: người trước → người kế tiếp trong cùng ca
    handovers: dict[tuple[str, str], int] = {}
    moves = events[["case_id", "resource"]].copy()
    moves["prev"] = moves.groupby("case_id")["resource"].shift(1)
    moves = moves[moves["prev"].notna() & (moves["prev"] != moves["resource"])]
    for (source, target), count in moves.groupby(["prev", "resource"]).size().items():
        handovers[(source, target)] = int(count)

    graph = nx.DiGraph()
    for _, r in stats.iterrows():
        graph.add_node(r["resource"])
    for (a, b), count in handovers.items():
        if graph.has_edge(a, b):
            graph[a][b]["weight"] += count
        else:
            graph.add_edge(a, b, weight=count)

    centrality = {}
    if graph.number_of_nodes():
        undirected = graph.to_undirected()
        centrality["degree"] = nx.degree_centrality(undirected)
        centrality["betweenness"] = nx.betweenness_centrality(graph) if graph.number_of_edges() else {n: 0.0 for n in graph}
        centrality["closeness"] = nx.closeness_centrality(graph) if graph.number_of_edges() else {n: 0.0 for n in graph}
        centrality["pagerank"] = nx.pagerank(graph, alpha=0.85) if graph.number_of_edges() else {n: 0.0 for n in graph}

    norm = {
        "degree": max(centrality.get("degree", {}).values(), default=1) or 1,
        "betweenness": max(centrality.get("betweenness", {}).values(), default=1) or 1,
        "closeness": max(centrality.get("closeness", {}).values(), default=1) or 1,
        "pagerank": max(centrality.get("pagerank", {}).values(), default=1) or 1,
    }
    table = []
    for node in nodes:
        name = node["resource"]
        score = (
            0.35 * centrality.get("degree", {}).get(name, 0) / norm["degree"]
            + 0.30 * centrality.get("betweenness", {}).get(name, 0) / norm["betweenness"]
            + 0.15 * centrality.get("closeness", {}).get(name, 0) / norm["closeness"]
            + 0.20 * centrality.get("pagerank", {}).get(name, 0) / norm["pagerank"]
        )
        table.append({
            **node,
            "degree": _num(centrality.get("degree", {}).get(name, 0), 3),
            "betweenness": _num(centrality.get("betweenness", {}).get(name, 0), 3),
            "closeness": _num(centrality.get("closeness", {}).get(name, 0), 3),
            "pagerank": _num(centrality.get("pagerank", {}).get(name, 0), 3),
            "score": _num(score, 3),
        })
    table.sort(key=lambda r: -(r["score"] or 0))

    links = [{"source": a, "target": b, "value": c} for (a, b), c in
             sorted(handovers.items(), key=lambda kv: -kv[1])]

    return {"nodes": nodes, "centrality": table, "links": links,
            "unit": snap.unit, "n_handovers": len(handovers)}


# ---------------------------------------------------------------------------
# Cảnh báo
# ---------------------------------------------------------------------------
def _label(activity: str) -> str:
    return models.ACTIVITY_LABELS.get(activity, activity)


def alerts(snap: Snapshot, limit: int = 200) -> dict:
    out: list[dict] = []
    unit = snap.unit
    events = snap.events
    rework_cases = 0

    for row in snap.cases.itertuples():
        std = row.std_last
        if row.is_open and std and row.dwell > std and not pd.isna(std):
            severity = "high" if row.dwell > std * 2 else "medium"
            out.append({
                "severity": severity,
                "kind": "quá hạn bước hiện tại",
                "case_id": row.case_id,
                "title": f"{row.case_id} đang ở “{_label(row.last_activity)}” quá định mức",
                "detail": f"Đã {_vn(row.dwell, 2)} {unit} trong bước, định mức {_vn(std, 2)} {unit}.",
                "metric": _num(row.dwell, 2),
                "threshold": _num(std, 2),
            })

        if row.late_share >= 60 and row.n_events >= 4:
            out.append({
                "severity": "medium",
                "kind": "ca nhiều bước quá hạn",
                "case_id": row.case_id,
                "title": f"{row.case_id} có {row.n_late}/{row.n_events} bước quá hạn",
                "detail": f"Tổng độ trễ tích luỹ {_vn(row.delay_total, 1)} {unit}.",
                "metric": _num(row.late_share, 1),
                "threshold": 60.0,
            })

        if row.rework > 0:
            rework_cases += 1

    if rework_cases:
        total_cases = len(snap.cases) or 1
        out.append({
            "severity": "low",
            "kind": "làm lại (rework)",
            "case_id": None,
            "title": f"{rework_cases} ca có bước bị lặp lại ({_vn(_pct(rework_cases, total_cases))}%)",
            "detail": "Phải thực hiện lại ít nhất một bước trong cùng ca — nguồn gốc của thời gian lãng phí.",
            "metric": rework_cases,
            "threshold": 0,
        })

    if "Rejected" in set(events["activity"]):
        rejected = set(snap.cases.loc[snap.cases["status"] == REJECTED, "case_id"])
        if rejected:
            worked = events[events["case_id"].isin(rejected) & events["activity"].isin(["In Progress", "In Test"])]
            for case_id, count in worked.groupby("case_id").size().items():
                out.append({
                    "severity": "medium",
                    "kind": "bị từ chối sau khi đã làm",
                    "case_id": case_id,
                    "title": f"{case_id} bị loại sau khi đã vào bước thực hiện",
                    "detail": f"Công sức đã bỏ: {int(count)} bước ở In Progress/In Test trước khi Rejected.",
                    "metric": int(count),
                    "threshold": 0,
                })

    # cảnh báo mức quy trình
    act = events.groupby("activity").agg(visits=("case_id", "size"), late=("is_late", "sum"))
    for activity, r in act.iterrows():
        share = _pct(r["late"], r["visits"])
        if r["visits"] >= 8 and share >= 60:
            out.append({
                "severity": "high",
                "kind": "điểm nghẽn quy trình",
                "case_id": None,
                "title": f"Điểm nghẽn: “{_label(activity)}” quá hạn {_vn(share)}%",
                "detail": f"{int(r['late'])}/{int(r['visits'])} lượt vượt định mức — cần chuẩn hoá bước này.",
                "metric": share,
                "threshold": 60.0,
            })

    order = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda a: (order.get(a["severity"], 3), -(a["metric"] or 0)))

    counts = {"high": 0, "medium": 0, "low": 0}
    for item in out:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1
    return {"items": out[:limit], "counts": counts, "total": len(out)}


# ---------------------------------------------------------------------------
# Siêu dữ liệu nguồn
# ---------------------------------------------------------------------------
def source_meta(log: EventLog) -> dict:
    presets = time_presets(log)
    model = models.model_for(log.key)
    return {
        "key": log.key,
        "label": log.label,
        "short": SOURCE_SHORT.get(log.key, log.label),
        "process_name": log.process_name,
        "unit": log.unit,
        "notes": log.notes,
        "file": log.meta.get("file_name"),
        "n_cases": int(log.events["case_id"].nunique()),
        "n_events": int(len(log.events)),
        "n_activities": int(log.events["activity"].nunique()),
        "n_resources": int(log.events["resource"].nunique()),
        "range": {"start": _ts(log.min_time), "end": _ts(log.max_time)},
        "presets": presets,
        "model_label": model["label"],
        "norms_note": log.meta.get("norms_note", "Định mức đọc từ bài toán gốc."),
        "activity_order": models.STATE_ORDER_HINT.get(
            log.key if log.key in models.STATE_ORDER_HINT else
            ("ticket" if log.key == "ticket" else "jira"), []),
    }
