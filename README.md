# Process Dashboard — Theo dõi & phân tích quy trình nghiệp vụ

Bản demo giao diện **process mining** dựng từ event log thật và event log bài tập:
giám sát vận hành (ca đang mở, tồn đọng, quá hạn), khai phá quy trình (DFG, biến thể,
tuân thủ) và phân tích nguồn lực (mạng bàn giao, centrality).

### ▶ [Mở bản demo](https://lilalinhlan.github.io/Bussiness-process-mining/)

---

## Tính năng

| Tab | Nội dung |
|---|---|
| **Tổng quan** | 8 KPI (số ca, số bước, đúng hạn/quá hạn, chu kỳ trung vị & P90, ca đang mở, ca trễ hạn), dòng sự kiện theo thời gian, cơ cấu trạng thái, phân bố chu kỳ, tỷ lệ đúng hạn từng bước |
| **Theo dõi vận hành** | Bảng ca có lọc theo trạng thái / nguồn lực / mã ca / ca quá hạn; bấm một dòng để xem dòng thời gian Gantt và chi tiết từng bước |
| **Cảnh báo** | Bước hiện tại quá hạn, ca nhiều bước trễ, làm lại (rework), bị từ chối sau khi đã làm, điểm nghẽn quy trình — xếp theo 3 mức |
| **Quy trình & tuân thủ** | DFG (Sankey) khai phá từ dữ liệu, luồng chuyển tiếp, top biến thể, mức khớp với quy trình chuẩn và các luồng lệch |
| **Nguồn lực & bàn giao** | Mạng bàn giao (mũi tên chỉ chiều chuyển việc), xếp hạng centrality (degree / betweenness / closeness / PageRank), hiệu suất từng người |

**Cỗ máy thời gian**: thanh *Thời điểm* cho phép tua về bất kỳ mốc nào trong khoảng dữ liệu
và xem quy trình đúng như nó đang diễn ra lúc đó — ca nào đang mở, kẹt ở bước nào, bao nhiêu ca trễ hạn.
Bốn mốc nhanh: **Đầu kỳ · Đỉnh tồn đọng · Giữa kỳ · Cuối kỳ**.

## Bộ dữ liệu

| Nguồn | Quy mô | Đơn vị thời gian | Định mức |
|---|---|---|---|
| Ticket CSKH (bài tập, BPMN Agent–Supervisor) | 30 ca · 180 bước · 5 nhân sự | phút | Bảng Standard Time của quy trình |
| Jira Bug (TI) | 161 issue · 875 lần đổi trạng thái | ngày làm việc | Phân vị 75 thời gian lưu lại mỗi trạng thái |
| Jira Story (TI) | 182 issue · 734 lần đổi trạng thái | ngày làm việc | như trên |
| Helpdesk (event log công khai 2010–2014) | 4.580 ca · 21.348 sự kiện · 22 nhân viên | ngày | như trên |

Hai nguồn Jira có **quy trình chuẩn** để đối chiếu (mô hình Bug). Story và Helpdesk chưa có
reference model nên tab tuân thủ chỉ phân tích khai phá, không chấm điểm.

## Cách hoạt động trên GitHub Pages

GitHub Pages chỉ phục vụ file tĩnh, không chạy được Python. Vì vậy số liệu được **đóng băng sẵn**:

- `docs/data/<nguồn>/pNN.json` — toàn bộ KPI, DFG, biến thể, centrality, cảnh báo đã tính cho từng mốc thời gian (22 mốc/nguồn)
- `docs/data/<nguồn>/events.json` — event log rút gọn; trình duyệt tự dựng **bảng ca** và **dòng thời gian của từng ca** từ file này, nhờ đó vẫn xem chi tiết ca và kéo thanh thời gian được
- `docs/index.html` + `docs/static/` — giao diện (cùng một `app.js` dùng cho cả chế độ Flask và chế độ tĩnh)

Tổng dung lượng dữ liệu: **~3,3 MB** cho 4 nguồn.

## Cấu trúc repo

```
.
├── docs/                 # site tĩnh → GitHub Pages (nhánh main, thư mục /docs)
│   ├── index.html
│   ├── static/{css,js,vendor}
│   └── data/{index.json, <nguồn>/…}
└── app/                  # mã nguồn: Flask + script xuất tĩnh
    ├── app.py            # web server + JSON API
    ├── build_static.py   # xuất dashboard thành site tĩnh (sinh ra docs/)
    ├── core/             # nạp dữ liệu, tính toán, mô hình quy trình chuẩn
    ├── templates/ static/
    └── README.md         # hướng dẫn chi tiết
```

## Chạy cục bộ

```bash
cd app
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5000
```

Để dựng lại site tĩnh (cần event log gốc đặt đúng vị trí mô tả trong `app/README.md`):

```bash
cd app
python build_static.py --out ../docs
```

## Ghi chú kỹ thuật

- **Không rò rỉ tương lai**: khi tua về quá khứ, bước đang diễn ra được cắt tại thời điểm quan sát,
  nên KPI của quá khứ không dùng thời lượng thật ghi trong file gốc.
- Toàn bộ giao diện và số liệu dùng tiếng Việt, định dạng số `vi-VN`.
- Biểu đồ vẽ bằng Plotly (nhúng nội bộ, không cần Internet).
