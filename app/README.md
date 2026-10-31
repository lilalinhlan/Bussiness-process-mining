# Process Dashboard — Theo dõi &amp; phân tích quy trình

Giao diện web (Flask + Plotly) để **giám sát vận hành** và **phân tích quy trình** trực tiếp từ
các event log có trong workspace (4 nguồn):

| Nguồn | File dữ liệu | Quy mô | Đơn vị thời gian |
|---|---|---|---|
| Đồ án 1 · Ticket CSKH | `BaiTap_ERP_Process_Mining/data/Event_Log_Quy_Trinh_Ticket_Bo_Sung_Danh_Gia.xlsx` | 30 ca · 180 bước · 6 hoạt động · 5 nhân sự | phút |
| Đồ án 2 · Jira Bug | `IS6003.11.CH/dataset/TIeventlogBug.csv` | 161 issue · 874 lần đổi trạng thái | ngày làm việc |
| Đồ án 2 · Jira Story | `IS6003.11.CH/dataset/TIeventlogStory.csv` | 182 issue · 733 lần đổi trạng thái | ngày làm việc |
| Dữ liệu thật · Helpdesk | `Helpdesk_event log.xlsx` (sheet `Helpdesk (2)`) | 4.580 ca · 21.348 sự kiện · 14 hoạt động · 22 nhân viên (2010–2014) | ngày |

Dashboard **không sửa, không sao chép** dữ liệu gốc — mọi con số đều tính lại từ file nguồn mỗi khi khởi động.

---

## Chạy

Cách nhanh nhất: **double-click `run.bat`** (script tự kiểm tra thư viện rồi mở trình duyệt).

Hoặc bằng dòng lệnh:

```powershell
cd "D:\UIT\Semester 3_2026-08\ERP\ProcessDashboard"
python -m pip install -r requirements.txt   # chỉ cần 1 lần
python app.py                               # tự mở http://127.0.0.1:5000
```

Tuỳ chọn:

```powershell
python app.py --port 8000 --no-browser
```

> **Lưu ý:** đây là Flask dev server nên **không tự chạy nền**. Sau khi tắt cửa sổ terminal
> hoặc khởi động lại máy, phải chạy lại `run.bat`. Nếu trình duyệt báo *không kết nối được* thì
> gần như chắc chắn server chưa chạy — kiểm tra cửa sổ terminal còn mở không.

> Plotly được phục vụ nội bộ từ `static/vendor/plotly.min.js` nên **không cần Internet**.

---

## Các màn hình

| Tab | Nội dung |
|---|---|
| **Tổng quan** | 8 KPI (số ca, số bước, đúng hạn/quá hạn, chu kỳ trung vị & P90, ca đang mở, ca trễ hạn hiện tại); dòng sự kiện theo ngày; cơ cấu trạng thái; phân bố chu kỳ; tỷ lệ đúng hạn từng bước; bảng điểm chi tiết |
| **Theo dõi vận hành** | Bảng ca có lọc theo trạng thái / nguồn lực / mã ca / ca quá hạn; bấm một dòng để mở **dòng thời gian Gantt**, đường đi của ca và bảng chi tiết từng bước |
| **Cảnh báo** | Cảnh báo theo 3 mức (nghiêm trọng / trung bình / thấp): bước hiện tại quá hạn, ca nhiều bước quá hạn, làm lại (rework), bị từ chối sau khi đã làm, điểm nghẽn quy trình |
| **Quy trình & tuân thủ** | DFG (Sankey) khai phá từ dữ liệu, bảng luồng chuyển tiếp, top biến thể, mức khớp với **mô hình chuẩn** (BPMN Agent–Supervisor / `reference_model` của đồ án Jira) và danh sách điểm lệch |
| **Nguồn lực & bàn giao** | Mạng bàn giao (mũi tên = chiều chuyển việc) + xếp hạng centrality (degree, betweenness, closeness, PageRank) + hiệu suất từng người |

### Cỗ máy thời gian

Thanh **Thời điểm** cho phép tua về bất kỳ lúc nào trong khoảng dữ liệu và xem quy trình
*đúng như nó đang diễn ra* tại thời điểm đó: ca nào đang mở, đang kẹt ở bước nào, bao nhiêu ca trễ hạn.
Bốn mốc nhanh: **Đầu kỳ · Đỉnh tồn đọng · Giữa kỳ · Cuối kỳ** (đỉnh tồn đọng được tìm bằng thuật toán sweep-line).

---

## Định nghĩa chỉ số

| Chỉ số | Cách tính |
|---|---|
| **Đúng hạn / Quá hạn** | So `thời lượng bước` với `định mức` của bước đó |
| **Định mức — Ticket** | Đọc từ sheet `Standard Time` trong file Excel gốc |
| **Định mức — Jira** | Phân vị 75 thời gian lưu lại của mỗi trạng thái (chỉ trạng thái có ≥ 10 lượt), đúng theo Quyết định 3 trong `IS6003.11.CH/configs/process.yaml`. Vì vậy tỷ lệ đúng hạn của Jira xấp xỉ 75% theo thiết kế — đây là **chuẩn nội suy**, không phải SLA thật |
| **Chu kỳ (cycle time)** | Từ bước đầu tiên đến khi ca kết thúc; ca còn mở thì tính đến thời điểm quan sát |
| **Đang mở** | Ca chưa chạm bước kết thúc (`Đóng ticket` / `DONE` / `Rejected`) tại thời điểm quan sát |
| **Trễ hạn hiện tại** | Ca đang mở và đã lưu ở bước hiện tại lâu hơn định mức |
| **Rework** | Số lần một bước/trạng thái bị lặp lại trong cùng một ca |
| **Tuân thủ** | % lần chuyển tiếp nằm trong mô hình chuẩn; % ca có **toàn bộ** đường đi khớp mô hình |

**Không rò rỉ tương lai:** khi tua về quá khứ, bước đang diễn ra được cắt tại thời điểm quan sát
(`_clip_to_as_of` trong `core/analytics.py`), nên KPI của quá khứ không dùng thời lượng thật trong file gốc.

---

## Cấu trúc mã nguồn

```
ProcessDashboard/
├── app.py                 Flask app + JSON API
├── build_static.py        xuất dashboard thành site tĩnh (GitHub Pages)
├── run.bat                khởi động nhanh trên Windows
├── requirements.txt
├── core/
│   ├── paths.py           đường dẫn dữ liệu gốc
│   ├── sources.py         bộ nạp & chuẩn hoá event log về một lược đồ chung
│   ├── analytics.py       snapshot theo thời điểm: KPI, bảng ca, DFG, biến thể, tuân thủ, cảnh báo
│   └── models.py          mô hình quy trình chuẩn (BPMN / reference_model) + nhãn hiển thị
├── templates/index.html
└── static/
    ├── css/app.css
    ├── js/app.js          giao diện, biểu đồ Plotly, drawer chi tiết ca
    └── vendor/plotly.min.js
```

### API

| Endpoint | Mô tả |
|---|---|
| `GET /api/sources` | Danh sách nguồn dữ liệu (chỉ metadata, không nạp cả file) |
| `GET /api/dashboard?source=&as_of=` | Toàn bộ số liệu của một nguồn tại một thời điểm |
| `GET /api/case/<case_id>?source=&as_of=` | Dòng thời gian chi tiết của một ca |

`source` nhận: `ticket`, `jira-bug`, `jira-story`, `helpdesk`.

---

## Xuất bản tĩnh (GitHub Pages)

```powershell
python build_static.py                    # → ../BPM-Demo/docs
python build_static.py --out ..\docs      # hoặc chỉ định thư mục đích
```

Script đóng băng số liệu thành JSON để chạy được trên hosting tĩnh:

- `data/<nguồn>/pNN.json`: KPI, DFG, biến thể, centrality, cảnh báo tại **22 mốc thời gian** mỗi nguồn
- `data/<nguồn>/events.json`: event log rút gọn → trình duyệt tự dựng bảng ca và dòng thời gian của ca
- `index.html` + `static/`: cùng giao diện; `app.js` tự nhận chế độ tĩnh qua `window.__STATIC__`

---

## Ghi chú kỹ thuật

- **Dữ liệu Jira** chỉ có `issueKey, timestamp, role, action`; trạng thái được rút từ action
  `update status to …`, `Issue created` → `CREATE`. Log không có tên cá nhân nên "nguồn lực" ở đây là **vai trò**.
- **Helpdesk** là log công khai (export từ Fluxicon Disco): mỗi dòng là một bước đã *complete* nên
  thời lượng bước = khoảng tới lần ghi nhận kế tiếp; tên nhân viên đã ẩn danh (`Value 1`…`Value 22`),
  không có định mức nên dùng P75. Chưa có reference model → tab tuân thủ hiện ghi chú.
- Hai lần đổi trạng thái trùng nhau liên tiếp trong cùng issue được gộp; khoảng cách < 60 giây được đánh dấu `cập nhật bù`.
- **Story chưa có mô hình chuẩn được duyệt** (đồ án 2 chỉ duyệt cho luồng Bug) nên tab tuân thủ hiển thị
  ghi chú thay vì chấm điểm — DFG và biến thể vẫn phân tích bình thường.
- Với log lớn (Helpdesk: 4.580 ca) bảng theo dõi phân trang 100 ca/lần; danh sách cảnh báo trả về tối đa
  200 mục ưu tiên mức cao nhất kèm tổng số thật.
- Toàn bộ giao diện và số liệu dùng tiếng Việt, định dạng số `vi-VN`.
