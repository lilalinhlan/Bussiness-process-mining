# -*- coding: utf-8 -*-
"""Nạp event log từ hai đồ án và chuẩn hoá về *một* lược đồ sự kiện chung.

Lược đồ chung (DataFrame ``events``) — mọi phân tích phía sau chỉ làm việc với nó:

    case_id     : mã ca / issue
    activity    : tên bước (hoặc trạng thái)
    resource    : người xử lý (với Jira: vai trò, vì log không có tên cá nhân)
    role        : vai trò của người xử lý
    start_time  : thời điểm bắt đầu bước (giờ địa phương, naive)
    end_time    : thời điểm kết thúc bước (NaN nếu bước cuối còn mở)
    duration    : thời lượng bước, theo đơn vị ``unit_key`` (NaN nếu còn mở)
    std         : định mức của bước, cùng đơn vị
    is_late     : duration > std
    delay       : max(0, duration - std)
    note        : ghi chú phụ (vd "cập nhật bù")

Hai đơn vị thời gian được dùng đúng theo bản chất dữ liệu:
  * ticket  -> phút (định mức cho sẵn trong file Excel)
  * jira    -> ngày làm việc (định mức suy ra = phân vị 75 thời gian lưu lại)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np
import pandas as pd

from . import paths

MINUTES = "minutes"
WORKDAYS = "workdays"
DAYS = "days"

UNIT_LABEL = {MINUTES: "phút", WORKDAYS: "ngày làm việc", DAYS: "ngày"}

EVENT_COLUMNS = [
    "case_id", "activity", "resource", "role",
    "start_time", "end_time", "duration", "std", "is_late", "delay", "note",
]


# ---------------------------------------------------------------------------
# Tiện ích thời gian
# ---------------------------------------------------------------------------
def workdays_between(t0: pd.Timestamp, t1: pd.Timestamp) -> float:
    """Số ngày làm việc (T2–T6, chu kỳ 24 giờ) trong khoảng [t0, t1)."""
    if pd.isna(t0) or pd.isna(t1) or t1 <= t0:
        return 0.0
    total = 0.0
    day = t0.normalize()
    while day < t1:
        nxt = day + pd.Timedelta(days=1)
        if day.weekday() < 5:
            total += (min(t1, nxt) - max(t0, day)).total_seconds()
        day = nxt
    return total / 86_400.0


def elapsed(t0: pd.Timestamp, t1: pd.Timestamp, unit_key: str) -> float:
    """Khoảng thời gian t0→t1 theo đơn vị của nguồn dữ liệu."""
    if pd.isna(t0) or pd.isna(t1):
        return 0.0
    if unit_key == MINUTES:
        return float((t1 - t0).total_seconds() / 60.0)
    if unit_key == DAYS:
        return float((t1 - t0).total_seconds() / 86_400.0)
    return workdays_between(t0, t1)



# ---------------------------------------------------------------------------
# Kiểu dữ liệu mô tả một event log đã chuẩn hoá
# ---------------------------------------------------------------------------
@dataclass
class EventLog:
    key: str
    label: str
    process_name: str
    events: pd.DataFrame
    unit_key: str
    start_activity: str
    terminal: tuple[str, ...]
    notes: str
    meta: dict = field(default_factory=dict)

    @property
    def unit(self) -> str:
        return UNIT_LABEL[self.unit_key]

    @property
    def min_time(self) -> pd.Timestamp:
        return self.events["start_time"].min()

    @property
    def max_time(self) -> pd.Timestamp:
        ends = self.events["end_time"].dropna()
        last_start = self.events["start_time"].max()
        last_end = ends.max() if len(ends) else last_start
        return max(last_start, last_end)


# ---------------------------------------------------------------------------
# Đồ án 1 — Event log quy trình Customer Service Ticket (Excel)
# ---------------------------------------------------------------------------
TICKET_ACTIVITY_ROLE = {
    "Tạo ticket": "Agent",
    "Chỉnh sửa thông tin ticket": "Agent",
    "Gửi yêu cầu phê duyệt": "Agent",
    "Đóng ticket": "Agent",
    "Cập nhật trạng thái ticket: Đồng ý": "Supervisor",
    "Cập nhật trạng thái ticket: Từ chối": "Supervisor",
}
TICKET_TERMINAL = ("Đóng ticket",)


def _read_ticket_norms(xlsx: pd.ExcelFile) -> dict[str, float]:
    norms: dict[str, float] = {}
    if "Standard Time" in xlsx.sheet_names:
        try:
            sheet = xlsx.parse("Standard Time", skiprows=1)
            sheet.columns = [str(c).strip().lower() for c in sheet.columns]
            act_col = sheet.columns[0]
            std_col = next((c for c in sheet.columns if "standard" in c), sheet.columns[1])
            for _, row in sheet.iterrows():
                act = str(row[act_col]).strip()
                if not act or act.lower() == "activity":
                    continue
                try:
                    norms[act] = float(row[std_col])
                except (TypeError, ValueError):
                    continue
        except Exception:  # pragma: no cover - dữ liệu lỗi hiếm
            pass
    return norms


def load_ticket_log() -> EventLog:
    path = paths.TICKET_XLSX
    if not path.is_file():
        raise FileNotFoundError(f"Không thấy event log ticket: {path}")

    xlsx = pd.ExcelFile(path)
    sheet = "Event Logs" if "Event Logs" in xlsx.sheet_names else xlsx.sheet_names[0]
    df = xlsx.parse(sheet, skiprows=1)
    df.columns = [str(c).strip().lower() for c in df.columns]

    df = df.rename(columns={
        "case id": "case_id", "case": "case_id",
        "task id": "task_id",
        "start time": "start_time", "end time": "end_time",
    })
    df = df.dropna(subset=["case_id", "activity"]).copy()

    df["case_id"] = df["case_id"].astype(str).str.strip()
    df["activity"] = df["activity"].astype(str).str.strip()
    df["resource"] = df["resource"].fillna("(không rõ)").astype(str).str.strip()
    df["start_time"] = pd.to_datetime(df["start_time"], errors="coerce")
    df["end_time"] = pd.to_datetime(df["end_time"], errors="coerce")
    df = df.dropna(subset=["start_time", "end_time"])

    norms = _read_ticket_norms(xlsx)
    if not norms:
        norms = {k: 10.0 for k in TICKET_ACTIVITY_ROLE}

    df["role"] = df["activity"].map(TICKET_ACTIVITY_ROLE).fillna("Agent")
    df["duration"] = (df["end_time"] - df["start_time"]).dt.total_seconds() / 60.0
    df["std"] = df["activity"].map(norms)
    df["note"] = ""
    df["case_id"] = df["case_id"].astype(str)

    # giữ nguyên thứ tự thời gian trong từng ca
    df = df.sort_values(["case_id", "start_time"]).reset_index(drop=True)

    df["is_late"] = df["duration"] > df["std"] + 1e-9
    df["delay"] = (df["duration"] - df["std"]).clip(lower=0)

    events = df[EVENT_COLUMNS].copy()
    return EventLog(
        key="ticket",
        label="Ticket CSKH (BPMN Agent–Supervisor)",
        process_name="Quy trình xử lý ticket dịch vụ khách hàng",
        events=events,
        unit_key=MINUTES,
        start_activity="Tạo ticket",
        terminal=TICKET_TERMINAL,
        notes="30 ca · 180 bước · định mức đọc từ sheet 'Standard Time'.",
        meta={
            "file": str(path),
            "file_name": path.name,
            "norms": norms,
            "role_map": TICKET_ACTIVITY_ROLE,
            "norms_note": "Định mức thời gian quy định cho từng bước của quy trình.",
        },
    )


# ---------------------------------------------------------------------------
# Đồ án 2 — Event log Jira (status log)
# ---------------------------------------------------------------------------
_JIRA_OFFSET = re.compile(r"([+-])(\d{2}):?(\d{2})$")
_STATUS_RE = re.compile(r"update status to ([^,]+)")


def _local_naive(series: pd.Series) -> pd.Series:
    """UTC timestamp + offset gốc trong chuỗi → giờ địa phương (naive)."""
    utc = pd.to_datetime(series, format="ISO8601", utc=True)
    offsets = series.astype(str).str.extract(_JIRA_OFFSET)
    sign = offsets[0].map({"-": -1, "+": 1}).fillna(0).astype(int)
    minutes = offsets[1].astype(float) * 60 + offsets[2].astype(float)
    delta = pd.to_timedelta(sign * minutes, unit="m")
    return (utc + delta.values).dt.tz_localize(None)


def _jira_states(actions: pd.Series) -> pd.Series:
    """Rút trạng thái đích từ chuỗi action; CREATE cho sự kiện tạo issue."""
    def one(action: str) -> str | None:
        text = str(action).strip()
        if text == "Issue created":
            return "CREATE"
        found = _STATUS_RE.search(text)
        return found.group(1).strip() if found else None

    return actions.map(one)


JIRA_TERMINAL = ("DONE", "Rejected")


def load_jira_log(kind: str) -> EventLog:
    path = paths.JIRA_BUG_CSV if kind == "bug" else paths.JIRA_STORY_CSV
    if not path.is_file():
        raise FileNotFoundError(f"Không thấy event log Jira: {path}")

    raw = pd.read_csv(path)
    raw.columns = [str(c).strip() for c in raw.columns]
    raw["case_id"] = raw["issueKey"].astype(str).str.strip()
    raw["role"] = raw["role"].fillna("unknown").astype(str).str.strip()
    raw["start_time"] = _local_naive(raw["timestamp"])
    raw["activity"] = _jira_states(raw["action"])
    raw = raw.dropna(subset=["activity"]).copy()
    raw = raw.sort_values(["case_id", "start_time"]).reset_index(drop=True)

    # bỏ lần lặp trạng thái liên tiếp trong cùng một ca
    same = (raw["activity"] == raw.groupby("case_id")["activity"].shift())
    raw = raw[~same].reset_index(drop=True)

    # duration của mỗi bước = tới lần đổi trạng thái kế tiếp
    nxt = raw.groupby("case_id")["start_time"].shift(-1)
    is_last = nxt.isna()
    gaps = (nxt - raw["start_time"]).dt.total_seconds() / 60.0
    raw["gap_minutes"] = gaps
    raw["end_time"] = nxt
    raw["duration"] = np.where(
        is_last,
        np.where(raw["activity"].isin(JIRA_TERMINAL), 0.0, np.nan),
        np.nan,
    )

    # tính duration theo ngày làm việc (vector hoá theo từng ca cho gọn)
    durations = np.full(len(raw), np.nan)
    starts = raw["start_time"].to_numpy()
    ends = raw["end_time"].to_numpy()
    for i in range(len(raw)):
        if pd.isna(ends[i]):
            durations[i] = 0.0 if raw["activity"].iat[i] in JIRA_TERMINAL else np.nan
        else:
            durations[i] = workdays_between(pd.Timestamp(starts[i]), pd.Timestamp(ends[i]))
    raw["duration"] = durations

    raw["resource"] = raw["role"]
    raw["note"] = np.where(raw["gap_minutes"] < 1.0, "cập nhật bù", "")

    # định mức = phân vị 75 thời gian lưu lại theo trạng thái (min 10 lượt)
    observed = raw["duration"].dropna()
    counts = raw.groupby("activity")["duration"].count()
    quantiles = raw.groupby("activity")["duration"].quantile(0.75)
    fallback = float(observed.quantile(0.75)) if len(observed) else 0.0
    norms = {
        act: (float(quantiles[act]) if counts.get(act, 0) >= 10 and not pd.isna(quantiles[act])
              else fallback)
        for act in counts.index
    }
    raw["std"] = raw["activity"].map(norms)

    raw["is_late"] = (raw["duration"].notna()) & (raw["duration"] > raw["std"] + 1e-9)
    raw["delay"] = (raw["duration"] - raw["std"]).clip(lower=0).fillna(0.0)

    events = raw[EVENT_COLUMNS].copy()
    label = "Jira – Bug (TI)" if kind == "bug" else "Jira – Story (TI)"
    return EventLog(
        key=f"jira-{kind}",
        label=label,
        process_name="Quy trình xử lý issue Jira (Inbox → DONE/Rejected)",
        events=events,
        unit_key=WORKDAYS,
        start_activity="CREATE",
        terminal=JIRA_TERMINAL,
        notes=(
            f"{events['case_id'].nunique()} issue · {len(events)} lần đổi trạng thái · "
            "định mức = P75 thời gian lưu lại mỗi trạng thái."
        ),
        meta={
            "file": str(path),
            "file_name": path.name,
            "norms": norms,
            "norms_note": "Phân vị 75 thời gian lưu lại (chỉ trạng thái có ≥ 10 lượt).",
            "action_variants": int(raw["action"].nunique()),
            "backfill_events": int((raw["gap_minutes"] < 1.0).sum()),
        },
    )


# ---------------------------------------------------------------------------
# Nguồn 4 — Event log Helpdesk thật (Fluxicon Disco export, 21.348 sự kiện)
# ---------------------------------------------------------------------------
HELPDESK_TERMINAL = ("Closed",)
_HELPDESK_DROP = ("concept:name", "org:resource", "lifecycle:transition",
                  "case:variant", "case:variant-index", "case:creator")


def load_helpdesk_log() -> EventLog:
    path = paths.HELPDESK_XLSX
    if not path.is_file():
        raise FileNotFoundError(f"Không thấy event log Helpdesk: {path}")

    xlsx = pd.ExcelFile(path)
    sheet = "Helpdesk (2)" if "Helpdesk (2)" in xlsx.sheet_names else xlsx.sheet_names[0]
    raw = xlsx.parse(sheet)

    raw = raw.rename(columns={
        "Activity": "activity",
        "Resource": "resource",
        "case:concept:name": "case_id",
        "time:timestamp": "timestamp",
    })
    raw = raw.drop(columns=[c for c in _HELPDESK_DROP if c in raw.columns])

    raw["case_id"] = raw["case_id"].astype(str).str.strip()
    raw["activity"] = raw["activity"].astype(str).str.strip()
    raw["resource"] = raw["resource"].fillna("(không rõ)").astype(str).str.strip()
    raw["start_time"] = pd.to_datetime(raw["timestamp"], errors="coerce")
    raw = raw.dropna(subset=["case_id", "activity", "start_time"])
    raw = raw.sort_values(["case_id", "start_time"]).reset_index(drop=True)

    # mỗi dòng là một bước đã hoàn tất → thời lượng = tới lần ghi nhận kế tiếp
    raw["end_time"] = raw.groupby("case_id")["start_time"].shift(-1)
    raw["duration"] = (raw["end_time"] - raw["start_time"]).dt.total_seconds() / 86_400.0
    last = raw["end_time"].isna()
    raw.loc[last & raw["activity"].isin(HELPDESK_TERMINAL), "duration"] = 0.0

    raw["role"] = "Helpdesk"
    raw["note"] = ""

    # định mức = phân vị 75 thời gian lưu lại mỗi bước (chỉ bước có ≥ 10 lượt)
    observed = raw["duration"].dropna()
    counts = raw.groupby("activity")["duration"].count()
    quantiles = raw.groupby("activity")["duration"].quantile(0.75)
    fallback = float(observed.quantile(0.75)) if len(observed) else 0.0
    norms = {
        act: (float(quantiles[act]) if counts.get(act, 0) >= 10 and not pd.isna(quantiles[act])
              else fallback)
        for act in counts.index
    }
    raw["std"] = raw["activity"].map(norms)

    raw["is_late"] = (raw["duration"].notna()) & (raw["duration"] > raw["std"] + 1e-9)
    raw["delay"] = (raw["duration"] - raw["std"]).clip(lower=0).fillna(0.0)

    events = raw[EVENT_COLUMNS].copy()
    return EventLog(
        key="helpdesk",
        label="Dữ liệu thật · Helpdesk",
        process_name="Quy trình helpdesk (ticket → phân loại → xử lý → đóng)",
        events=events,
        unit_key=DAYS,
        start_activity="Insert ticket",
        terminal=HELPDESK_TERMINAL,
        notes=(
            f"{events['case_id'].nunique()} ca · {len(events)} sự kiện · "
            "export từ Fluxicon Disco · định mức = P75 thời gian lưu lại mỗi bước."
        ),
        meta={
            "file": str(path),
            "file_name": path.name,
            "norms": norms,
            "norms_note": "Phân vị 75 thời gian lưu lại (chỉ bước có ≥ 10 lượt).",
            "source_note": "Event log Helpdesk công khai (2010–2014), tên nhân viên đã ẩn danh.",
        },
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
LOADERS = {
    "ticket": load_ticket_log,
    "jira-bug": lambda: load_jira_log("bug"),
    "jira-story": lambda: load_jira_log("story"),
    "helpdesk": load_helpdesk_log,
}

SOURCE_LABELS = {
    "ticket": "Đồ án 1 · Ticket CSKH",
    "jira-bug": "Đồ án 2 · Jira Bug",
    "jira-story": "Đồ án 2 · Jira Story",
    "helpdesk": "Dữ liệu thật · Helpdesk",
}

# Nhãn ngắn cho thanh chuyển nguồn dữ liệu
SOURCE_SHORT = {
    "ticket": "Ticket CSKH",
    "jira-bug": "Jira Bug",
    "jira-story": "Jira Story",
    "helpdesk": "Helpdesk (thật)",
}

# Đường dẫn nguồn — kiểm tra tồn tại mà không cần đọc cả file
SOURCE_PATHS = {
    "ticket": lambda: paths.TICKET_XLSX,
    "jira-bug": lambda: paths.JIRA_BUG_CSV,
    "jira-story": lambda: paths.JIRA_STORY_CSV,
    "helpdesk": lambda: paths.HELPDESK_XLSX,
}
