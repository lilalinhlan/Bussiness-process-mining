# -*- coding: utf-8 -*-
"""Lõi xử lý dữ liệu của Process Dashboard."""

import warnings

# openpyxl cảnh báo về extension trong file Excel gốc — không ảnh hưởng dữ liệu đọc được
warnings.filterwarnings("ignore", message=".*(Unknown extension|Conditional Formatting).*")
