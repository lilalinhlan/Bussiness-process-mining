# -*- coding: utf-8 -*-
"""Mô hình quy trình chuẩn (reference model) dùng cho phân tích tuân thủ.

Hai mô hình được lấy đúng theo thiết kế đã có trong từng đồ án:
  * ticket  — sơ đồ BPMN swimlane Agent/Supervisor (BP_Customer service_ticket, Page-2)
  * jira    — `reference_model.arcs` trong IS6003.11.CH/configs/process.yaml (đã được duyệt)
"""

from __future__ import annotations

TICKET_ARCS = (
    ("Tạo ticket", "Chỉnh sửa thông tin ticket"),
    ("Chỉnh sửa thông tin ticket", "Gửi yêu cầu phê duyệt"),
    ("Gửi yêu cầu phê duyệt", "Cập nhật trạng thái ticket: Đồng ý"),
    ("Gửi yêu cầu phê duyệt", "Cập nhật trạng thái ticket: Từ chối"),
    ("Cập nhật trạng thái ticket: Đồng ý", "Đóng ticket"),
    ("Cập nhật trạng thái ticket: Từ chối", "Chỉnh sửa thông tin ticket"),
)

JIRA_ARCS = (
    ("CREATE", "Inbox"),
    ("CREATE", "To Investigate"),
    ("CREATE", "Rejected"),
    ("Inbox", "To Investigate"),
    ("Inbox", "Rejected"),
    ("To Investigate", "INVESTIGATED"),
    ("To Investigate", "Rejected"),
    ("INVESTIGATED", "To Do"),
    ("INVESTIGATED", "Rejected"),
    ("To Do", "In Progress"),
    ("To Do", "Rejected"),
    ("In Progress", "In Test"),
    ("In Test", "In Progress"),
    ("In Test", "DONE"),
)

REFERENCE_MODELS = {
    "ticket": {
        "reachable_nodes": {a for arc in TICKET_ARCS for a in arc},
        "arcs": set(TICKET_ARCS),
        "label": "BPMN Agent–Supervisor",
        "source": "BP_Customer service_ticket.drawio · Page-2",
        "approved": True,
    },
    "jira-bug": {
        "reachable_nodes": {a for arc in JIRA_ARCS for a in arc},
        "arcs": set(JIRA_ARCS),
        "label": "Quy trình chuẩn Jira Bug",
        "source": "IS6003.11.CH/configs/process.yaml · reference_model.arcs",
        "approved": True,
    },
    # Đồ án 2 chỉ duyệt mô hình chuẩn cho Bug; Story chỉ đặt cạnh để đối chiếu.
    "jira-story": {
        "reachable_nodes": set(),
        "arcs": set(),
        "label": "Chưa có quy trình chuẩn cho Story",
        "source": "",
        "approved": False,
    },
    # Nguồn ngoài, chưa có reference model được duyệt → chỉ phân tích khai phá
    "helpdesk": {
        "reachable_nodes": set(),
        "arcs": set(),
        "label": "Chưa có quy trình chuẩn cho Helpdesk",
        "source": "",
        "approved": False,
    },
}

# Nhãn hiển thị thân thiện cho các bước có tên kỹ thuật / quá dài
ACTIVITY_LABELS = {
    "CREATE": "CREATE · tạo issue",
    "OPEN": "OPEN",
    "Triage": "Triage · phân loại",
    "Chỉnh sửa thông tin ticket": "Chỉnh sửa thông tin",
    "Cập nhật trạng thái ticket: Đồng ý": "Phê duyệt: Đồng ý",
    "Cập nhật trạng thái ticket: Từ chối": "Phê duyệt: Từ chối",
}

# Thứ tự trạng thái để phát hiện "lùi trạng thái" ở log Jira
STATE_ORDER_HINT = {
    "ticket": [
        "Tạo ticket",
        "Chỉnh sửa thông tin ticket",
        "Gửi yêu cầu phê duyệt",
        "Cập nhật trạng thái ticket: Đồng ý",
        "Cập nhật trạng thái ticket: Từ chối",
        "Đóng ticket",
    ],
    "jira": [
        "CREATE", "Inbox", "To Investigate", "INVESTIGATED",
        "To Do", "In Progress", "In Test", "DONE", "Rejected",
    ],
    "helpdesk": [
        "Insert ticket", "Assign seriousness", "Take in charge ticket",
        "Wait", "Require upgrade", "Create SW anomaly", "Resolve SW anomaly",
        "Schedule intervention", "Resolve ticket", "Closed",
    ],
}


def model_for(source_key: str) -> dict:
    return REFERENCE_MODELS.get(source_key, REFERENCE_MODELS["ticket"])
