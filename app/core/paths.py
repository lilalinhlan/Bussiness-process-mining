# -*- coding: utf-8 -*-
"""Đường dẫn dữ liệu dùng cho dashboard.

Dashboard đọc trực tiếp dữ liệu gốc của các đồ án trong workspace, không sửa
hay sao chép chúng.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
ERP_ROOT = PROJECT_DIR.parent

# --- Đồ án 1: event log ticket CSKH (BPMN Agent - Supervisor) ---
TICKET_DIR = ERP_ROOT / "BaiTap_ERP_Process_Mining"
TICKET_XLSX = TICKET_DIR / "data" / "Event_Log_Quy_Trinh_Ticket_Bo_Sung_Danh_Gia.xlsx"

# --- Nguồn ngoài: event log Helpdesk thật (Fluxicon Disco export) đặt ở gốc workspace ---
HELPDESK_XLSX = ERP_ROOT / "Helpdesk_event log.xlsx"

# --- Đồ án 2: event log Jira (TI bug / story) ---
JIRA_DIR = ERP_ROOT / "IS6003.11.CH"
JIRA_BUG_CSV = JIRA_DIR / "dataset" / "TIeventlogBug.csv"
JIRA_STORY_CSV = JIRA_DIR / "dataset" / "TIeventlogStory.csv"

