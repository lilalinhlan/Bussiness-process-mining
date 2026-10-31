/* Process Dashboard — giao diện theo dõi & phân tích quy trình */
'use strict';

const C = {
  primary: '#4f46e5',
  primarySoft: 'rgba(79,70,229,0.16)',
  green: '#12b76a',
  red: '#f04438',
  amber: '#f79009',
  cyan: '#0891b2',
  violet: '#7a5af8',
  slate: '#94a3b8',
  grid: '#eef2f7',
  text: '#475467',
};

const CASE_PAGE = 100;

const state = {
  sources: [],
  source: null,
  asOf: null,
  data: null,
  tab: 'overview',
  filters: { status: '', q: '', resource: '', late: false },
  caseLimit: CASE_PAGE,
  alertSev: '',
  activityLabels: {},
  loadingCount: 0,
  fetchToken: 0,
};

/* ------------------------------------------------------------------ utils */
const IS_STATIC = Boolean(window.__STATIC__);
const store = { index: null, events: {} };

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const nf = (digits = 1) =>
  new Intl.NumberFormat('vi-VN', { maximumFractionDigits: digits, minimumFractionDigits: 0 });

function fmtNum(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return nf(digits).format(value);
}

function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

function fmtDateTime(iso, withTime = true) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const date = d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' });
  if (!withTime) return date;
  const time = d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
  return `${date} ${time}`;
}

function esc(text) {
  return String(text ?? '').replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
}

function activityLabel(name) {
  return state.activityLabels[name] || name;
}

function toast(message, isError = false) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.toggle('error', Boolean(isError));
  el.classList.add('show');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => el.classList.remove('show'), 2800);
}

function showLoading(on) {
  state.loadingCount = Math.max(0, state.loadingCount + (on ? 1 : -1));
  $('#loading').classList.toggle('show', state.loadingCount > 0);
}

async function api(url) {
  showLoading(true);
  try {
    const response = await fetch(url);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `Lỗi ${response.status}`);
    return payload;
  } finally {
    showLoading(false);
  }
}

/** Gọi API có thử lại — server dev có thể đang khởi động lại trong giây lát. */
async function apiRetry(url, attempts = 3) {
  let lastError;
  for (let i = 0; i < attempts; i += 1) {
    try {
      return await api(url);
    } catch (error) {
      lastError = error;
      if (i < attempts - 1) {
        await new Promise((resolve) => setTimeout(resolve, 700 * (i + 1)));
      }
    }
  }
  throw lastError;
}

/** Đọc file JSON tĩnh (chế độ GitHub Pages). */
async function json(url) {
  const response = await fetch(url, { cache: 'force-cache' });
  if (!response.ok) throw new Error(`Không tải được ${url} (${response.status})`);
  return response.json();
}

/* ------------------------------------------------------------------ plotly */
const PLOT_CONFIG = { displayModeBar: false, responsive: true, locale: 'vi' };

function baseLayout(extra = {}) {
  return Object.assign({
    margin: { l: 52, r: 18, t: 12, b: 40 },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: 'Segoe UI, Inter, system-ui, sans-serif', size: 11.5, color: C.text },
    hoverlabel: { bgcolor: '#101828', font: { color: '#fff', size: 12 }, bordercolor: '#101828' },
    xaxis: { gridcolor: C.grid, zeroline: false, linecolor: C.grid, automargin: true },
    yaxis: { gridcolor: C.grid, zeroline: false, linecolor: C.grid, automargin: true },
    showlegend: false,
    bargap: 0.28,
  }, extra);
}

function plot(el, traces, layout, config = PLOT_CONFIG, attempt = 0) {
  if (!el) return;
  if (typeof Plotly === 'undefined') {
    el.innerHTML = '<div class="empty">Không tải được thư viện biểu đồ (plotly.min.js).</div>';
    return;
  }
  // Tab vừa hiện ra có thể chưa có kích thước → chờ khung hình sau rồi vẽ lại
  if (!el.clientWidth || !el.clientHeight) {
    if (attempt < 10) {
      requestAnimationFrame(() => plot(el, traces, layout, config, attempt + 1));
    }
    return;
  }
  Plotly.react(el, traces, layout, config);
  Plotly.Plots.resize(el);
}

function resizeCharts(root = document) {
  $$('.chart', root).forEach((el) => {
    if (el.clientWidth && el.querySelector('svg')) Plotly.Plots.resize(el);
  });
}

function emptyChart(el, message) {
  if (!el) return;
  Plotly.purge(el);
  el.innerHTML = `<div class="empty">${esc(message)}</div>`;
}

/* ------------------------------------------------------------------ tables */
function renderTable(container, columns, rows, options = {}) {
  if (!container) return;
  if (!rows || !rows.length) {
    container.innerHTML = `<div class="empty">${esc(options.empty || 'Không có dữ liệu')}</div>`;
    return;
  }
  const head = columns.map((col) => {
    const cls = [col.align === 'right' ? 'num' : '', col.hide ? `hide-${col.hide}` : ''].filter(Boolean).join(' ');
    return `<th class="${cls}">${esc(col.label)}</th>`;
  }).join('');
  const body = rows.map((row) => {
    const cells = columns.map((col) => {
      const value = col.render ? col.render(row) : esc(row[col.key] ?? '—');
      const cls = [col.align === 'right' ? 'num' : '', col.cls || '', col.hide ? `hide-${col.hide}` : ''].filter(Boolean).join(' ');
      return `<td class="${cls}">${value}</td>`;
    }).join('');
    const rowClass = options.rowClass ? options.rowClass(row) : '';
    const dataAttr = options.rowAttr ? ` ${options.rowAttr(row)}` : '';
    return `<tr class="${rowClass}"${dataAttr}>${cells}</tr>`;
  }).join('');
  container.innerHTML = `<div class="table-wrap"><table class="data"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  if (options.onRowClick) {
    $$('tr[data-row]', container).forEach((tr) => {
      tr.addEventListener('click', () => options.onRowClick(tr.dataset.row));
    });
  }
}

function statusBadge(status) {
  const map = {
    'Hoàn thành': 'done',
    'Bị từ chối': 'rejected',
    'Đang mở': 'open',
  };
  return `<span class="badge ${map[status] || 'plain'}">${esc(status)}</span>`;
}

function barCell(pct, mode = 'good') {
  if (pct === null || pct === undefined) return '—';
  const value = Math.max(0, Math.min(100, pct));
  let level = 'info';
  if (mode === 'good') level = value >= 70 ? '' : value >= 40 ? 'warn' : 'bad';
  else if (mode === 'bad') level = value >= 60 ? 'bad' : value >= 30 ? 'warn' : '';
  return `<div class="bar-cell"><div class="bar-track"><div class="bar-fill ${level}" style="width:${value}%"></div></div><span class="bar-value">${fmtNum(value, 1)}%</span></div>`;
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  bindNav();
  bindFilters();
  bindDrawer();
  try {
    if (IS_STATIC) {
      store.index = await json('data/index.json');
      state.sources = store.index.sources || [];
    } else {
      const payload = await apiRetry('/api/sources');
      state.sources = (payload.sources || []).filter((s) => !s.error);
    }
    if (!state.sources.length) {
      toast('Không tìm thấy dữ liệu event log', true);
      return;
    }
    renderSourceSwitch();
    await loadSource(state.sources[0].key, null);
  } catch (error) {
    toast(`Không tải được dữ liệu (${error.message}).`, true);
    $('#sourceInfo').textContent = 'Không tải được dữ liệu';
    $('#pageSub').textContent = IS_STATIC
      ? 'Không đọc được thư mục data/. Hãy kiểm tra lại bản xuất tĩnh.'
      : 'Máy chủ chưa phản hồi. Đảm bảo cửa sổ Process Dashboard còn mở rồi tải lại trang (F5).';
  }
}

function renderSourceSwitch() {
  const wrap = $('#sourceSwitch');
  wrap.innerHTML = state.sources.map((s) =>
    `<button data-source="${esc(s.key)}" class="${s.key === state.source ? 'active' : ''}">${esc(s.short || s.label)}</button>`
  ).join('');
  $$('button', wrap).forEach((btn) => {
    btn.addEventListener('click', () => {
      if (btn.dataset.source === state.source) return;
      loadSource(btn.dataset.source, null);
    });
  });
}

function renderSourceInfo() {
  const meta = state.sourceMeta;
  const host = $('#sourceInfo');
  if (!meta) { host.textContent = 'Đang tải dữ liệu…'; return; }
  host.innerHTML =
    `<b>${esc(meta.file || '')}</b><br>` +
    `${fmtNum(meta.n_cases, 0)} ca · ${fmtNum(meta.n_events, 0)} sự kiện<br>` +
    `${esc(meta.range.start?.slice(0, 10) || '')} → ${esc(meta.range.end?.slice(0, 10) || '')}`;
}

async function loadSource(key, asOf) {
  state.source = key;
  state.data = null;
  state.sourceMeta = null;
  renderSourceSwitch();
  renderSourceInfo();
  if (IS_STATIC && !store.events[key]) {
    const entry = state.sources.find((s) => s.key === key);
    showLoading(true);
    try {
      store.events[key] = await json(entry.events);
    } finally {
      showLoading(false);
    }
  }
  await fetchDashboard(asOf || null);
}

function nearestPoint(entry, asOf) {
  const points = entry.points || [];
  if (!points.length) return null;
  if (!asOf) return points[points.length - 1];
  const target = Date.parse(asOf);
  let best = points[0];
  let bestDiff = Infinity;
  points.forEach((point) => {
    const diff = Math.abs(Date.parse(point.as_of) - target);
    if (diff < bestDiff) { best = point; bestDiff = diff; }
  });
  return best;
}

async function fetchDashboard(asOf) {
  const token = ++state.fetchToken;
  try {
    let payload;
    if (IS_STATIC) {
      const entry = state.sources.find((s) => s.key === state.source);
      const point = nearestPoint(entry, asOf);
      payload = await json(`data/${entry.key}/p${String(point.i).padStart(2, '0')}.json`);
      payload.meta = entry;
      payload.as_of = point.as_of;
      payload.activity_labels = store.index.activity_labels;
      payload.cases = computeCases(entry, point.as_of);
    } else {
      const url = `/api/dashboard?source=${encodeURIComponent(state.source)}`
        + (asOf ? `&as_of=${encodeURIComponent(asOf)}` : '');
      payload = await apiRetry(url, 2);
    }
    if (token !== state.fetchToken) return; // đã có yêu cầu mới hơn → bỏ kết quả cũ
    state.data = payload;
    state.asOf = payload.as_of;
    state.sourceMeta = payload.meta;
    state.activityLabels = payload.activity_labels || {};
    state.caseLimit = CASE_PAGE;
    renderPresets(payload.meta);
    renderSourceInfo();
    syncAsOfSlider();
    renderTab(state.tab);
    requestAnimationFrame(() => resizeCharts());
  } catch (error) {
    if (token !== state.fetchToken) return;
    toast(error.message, true);
  }
}

/* ------------------------------------------------------------------ header */
function renderPresets(meta) {
  const presets = meta?.presets;
  const host = $('#presets');
  if (!presets) { host.innerHTML = ''; return; }
  const items = [
    { key: 'start', label: 'Đầu kỳ', value: presets.start },
    { key: 'peak', label: `Đỉnh tồn đọng (${presets.peak_open} ca)`, value: presets.peak },
    { key: 'mid', label: 'Giữa kỳ', value: presets.mid },
    { key: 'end', label: 'Cuối kỳ', value: presets.end },
  ];
  host.innerHTML = `<span class="control-label">Mốc</span>` + items.map((item) =>
    `<button class="btn" data-asof="${esc(item.value)}">${esc(item.label)}</button>`
  ).join('');
  $$('button', host).forEach((btn) => {
    btn.addEventListener('click', () => {
      if (btn.dataset.asof && btn.dataset.asof !== state.asOf) fetchDashboard(btn.dataset.asof);
    });
  });
}

function syncAsOfSlider() {
  const meta = state.sourceMeta;
  if (!meta) return;
  const start = new Date(meta.presets.start).getTime();
  const end = new Date(meta.presets.end).getTime();
  const now = new Date(state.asOf).getTime();
  const ratio = end > start ? (now - start) / (end - start) : 1;
  $('#asOfRange').value = String(Math.round(ratio * 1000));
  $('#asOfReadout').textContent = fmtDateTime(state.asOf);
  updatePageHead();
}

function updatePageHead() {
  const meta = state.sourceMeta;
  const data = state.data;
  if (!meta || !data) return;
  const titles = {
    overview: ['Tổng quan quy trình', `${meta.process_name} — số liệu tại thời điểm quan sát.`],
    tracking: ['Theo dõi vận hành', 'Danh sách ca, thời gian lưu lại ở bước hiện tại và tình trạng quá hạn.'],
    alerts: ['Cảnh báo', 'Các ca và điểm nghẽn cần can thiệp, xếp theo mức độ nghiêm trọng.'],
    process: ['Quy trình & tuân thủ', 'Mô hình khai phá từ dữ liệu, biến thể và mức độ khớp với mô hình chuẩn.'],
    resources: ['Nguồn lực & bàn giao', 'Ai đang xử lý bước nào, bàn giao cho ai và mức độ quan trọng.'],
  };
  const [title, sub] = titles[state.tab] || titles.overview;
  $('#pageTitle').textContent = title;
  $('#pageSub').textContent = `${sub} ${meta.norms_note}`;
}

/* ------------------------------------------------------------------ nav */
function bindNav() {
  $$('#nav .nav-item').forEach((btn) => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });
  const range = $('#asOfRange');
  range.addEventListener('input', () => {
    const meta = state.sourceMeta;
    if (!meta) return;
    const start = new Date(meta.presets.start).getTime();
    const end = new Date(meta.presets.end).getTime();
    const ratio = Number(range.value) / 1000;
    $('#asOfReadout').textContent = fmtDateTime(new Date(start + (end - start) * ratio).toISOString());
  });
  range.addEventListener('change', () => {
    const meta = state.sourceMeta;
    if (!meta) return;
    const start = new Date(meta.presets.start).getTime();
    const end = new Date(meta.presets.end).getTime();
    const ratio = Number(range.value) / 1000;
    const stamp = new Date(start + (end - start) * ratio);
    const iso = new Date(stamp.getTime() - stamp.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
    fetchDashboard(iso);
  });
}

function switchTab(tab) {
  state.tab = tab;
  $$('#nav .nav-item').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
  $$('.tab-panel').forEach((p) => p.classList.toggle('active', p.id === `tab-${tab}`));
  updatePageHead();
  // để trình duyệt tính xong layout của panel mới rồi mới vẽ biểu đồ
  requestAnimationFrame(() => {
    renderTab(tab);
    requestAnimationFrame(() => resizeCharts(document.querySelector(`#tab-${tab}`)));
  });
  $('#main').scrollTo({ top: 0, behavior: 'smooth' });
}

function renderTab(tab) {
  if (!state.data) return;
  updatePageHead();
  try {
    if (tab === 'overview') renderOverview();
    else if (tab === 'tracking') renderTracking();
    else if (tab === 'alerts') renderAlerts();
    else if (tab === 'process') renderProcess();
    else if (tab === 'resources') renderResources();
  } catch (error) {
    console.error(error);
    toast(`Lỗi hiển thị tab: ${error.message}`, true);
  }
}

/* ------------------------------------------------------------------ overview */
function renderOverview() {
  const { overview } = state.data;

  $('#kpiGrid').innerHTML = overview.kpi.map((k) => `
    <div class="card kpi ${esc(k.tone)}">
      <div class="kpi-label">${esc(k.label)}</div>
      <div class="kpi-value">${fmtNum(k.value, k.unit === '%' ? 1 : 1)}<small>${esc(k.unit)}</small></div>
      <div class="kpi-hint">${esc(k.hint)}</div>
    </div>`).join('');

  renderDailyChart(overview);
  renderStatusChart(overview);
  renderCycleChart(overview);
  renderActivityChart(overview);
  renderActivityTable(overview);
}

function renderDailyChart({ daily }) {
  const el = $('#chartDaily');
  if (!daily.dates.length) { emptyChart(el, 'Không có dữ liệu theo ngày'); return; }
  const hint = $('#dailyHint');
  if (hint) hint.textContent = `Tổng hợp theo ${daily.granularity || 'ngày'} · số bước, ca mở mới và ca kết thúc`;
  const traces = [
    {
      type: 'bar', name: `Sự kiện / ${daily.granularity || 'ngày'}`, x: daily.dates, y: daily.events,
      marker: { color: C.primarySoft, line: { color: C.primary, width: 1 } },
      hovertemplate: `%{x|${daily.tickformat || '%d/%m'}}<br>%{y} sự kiện<extra></extra>`,
    },
    {
      type: 'scatter', mode: 'lines+markers', name: 'Ca mở mới', x: daily.dates, y: daily.started,
      line: { color: C.green, width: 2 }, marker: { size: 5 },
      yaxis: 'y2', hovertemplate: `%{x|${daily.tickformat || '%d/%m'}}<br>%{y} ca mở<extra></extra>`,
    },
    {
      type: 'scatter', mode: 'lines+markers', name: 'Ca kết thúc', x: daily.dates, y: daily.finished,
      line: { color: C.amber, width: 2, dash: 'dot' }, marker: { size: 5 },
      yaxis: 'y2', hovertemplate: `%{x|${daily.tickformat || '%d/%m'}}<br>%{y} ca kết thúc<extra></extra>`,
    },
  ];
  const layout = baseLayout({
    showlegend: true,
    legend: { orientation: 'h', y: 1.12, x: 0, font: { size: 11 } },
    margin: { l: 48, r: 48, t: 34, b: 40 },
    xaxis: { gridcolor: C.grid, type: 'date', tickformat: daily.tickformat || '%d/%m', automargin: true },
    yaxis: { gridcolor: C.grid, zeroline: false, rangemode: 'tozero', title: { text: 'Sự kiện', font: { size: 11 } } },
    yaxis2: {
      overlaying: 'y', side: 'right', showgrid: false, zeroline: false, rangemode: 'tozero',
      tickformat: 'd', title: { text: 'Ca', font: { size: 11 } },
    },
  });
  plot(el, traces, layout);
}

function renderStatusChart({ status_mix }) {
  const el = $('#chartStatus');
  if (!status_mix.values.length) { emptyChart(el, 'Không có ca'); return; }
  const colorMap = { 'Hoàn thành': C.green, 'Bị từ chối': C.red, 'Đang mở': C.primary };
  const colors = status_mix.labels.map((l) => colorMap[l] || C.slate);
  const total = status_mix.values.reduce((a, b) => a + b, 0);
  plot(el, [{
    type: 'pie', hole: 0.64,
    labels: status_mix.labels, values: status_mix.values,
    marker: { colors, line: { color: '#fff', width: 3 } },
    textinfo: 'none',
    hovertemplate: '%{label}: %{value} ca (%{percent})<extra></extra>',
  }], baseLayout({
    showlegend: true,
    legend: { orientation: 'h', y: -0.05, font: { size: 11 } },
    margin: { l: 10, r: 10, t: 10, b: 10 },
    annotations: [{
      text: `<b style="font-size:22px">${total}</b><br><span style="font-size:11px;color:#667085">ca</span>`,
      showarrow: false, font: { size: 15, color: '#101828' },
    }],
  }));
}

function renderCycleChart({ cycle_hist }) {
  const el = $('#chartCycle');
  if (!cycle_hist.x.length) { emptyChart(el, 'Chưa có ca kết thúc'); return; }
  plot(el, [{
    type: 'bar', x: cycle_hist.x, y: cycle_hist.y,
    marker: { color: 'rgba(122,90,248,0.75)', line: { color: C.violet, width: 1 } },
    hovertemplate: '%{x} ' + state.data.overview.unit + '<br>%{y} ca<extra></extra>',
  }], baseLayout({
    xaxis: { gridcolor: C.grid, title: { text: `Thời gian chu kỳ (${state.data.overview.unit})`, font: { size: 11 } }, automargin: true },
    yaxis: { gridcolor: C.grid, title: { text: 'Số ca', font: { size: 11 } }, automargin: true },
  }));
}

function renderActivityChart({ activity_rows }) {
  const el = $('#chartActivity');
  if (!activity_rows.length) { emptyChart(el, 'Không có dữ liệu'); return; }
  const rows = [...activity_rows].sort((a, b) => a.on_time_pct - b.on_time_pct);
  plot(el, [{
    type: 'bar', orientation: 'h',
    y: rows.map((r) => activityLabel(r.activity)),
    x: rows.map((r) => r.on_time_pct),
    customdata: rows.map((r) => [r.visits, r.late, r.avg_duration, r.std]),
    marker: {
      color: rows.map((r) => (r.on_time_pct >= 70 ? C.green : r.on_time_pct >= 45 ? C.amber : C.red)),
    },
    hovertemplate: '<b>%{y}</b><br>Đúng hạn: %{x}%<br>%{customdata[0]} lượt · %{customdata[1]} quá hạn<extra></extra>',
  }], baseLayout({
    margin: { l: 190, r: 46, t: 10, b: 36 },
    xaxis: { gridcolor: C.grid, range: [0, 100], ticksuffix: '%', automargin: true },
    yaxis: { gridcolor: 'rgba(0,0,0,0)', automargin: true, tickfont: { size: 11 } },
  }));
}

function renderActivityTable({ activity_rows, unit }) {
  renderTable($('#activityTable'), [
    { key: 'activity', label: 'Bước', render: (r) => `<b>${esc(activityLabel(r.activity))}</b>` },
    { key: 'visits', label: 'Số lượt', align: 'right', render: (r) => fmtNum(r.visits, 0) },
    { key: 'std', label: `Định mức (${esc(unit)})`, align: 'right', render: (r) => fmtNum(r.std, 2) },
    { key: 'avg_duration', label: `Thực tế TB (${esc(unit)})`, align: 'right', render: (r) => fmtNum(r.avg_duration, 2) },
    { key: 'delay', label: 'Tổng trễ', align: 'right', render: (r) => fmtNum(r.delay, 1) },
    { key: 'on_time_pct', label: 'Đúng hạn', render: (r) => barCell(r.on_time_pct) },
  ], activity_rows);
}

/* ------------------------------------------------------------------ tracking */
function bindFilters() {
  const onChange = (mutate) => (event) => {
    mutate(event.target);
    state.caseLimit = CASE_PAGE;
    renderTracking();
  };
  $('#filterStatus').addEventListener('change', onChange((el) => { state.filters.status = el.value; }));
  $('#filterResource').addEventListener('change', onChange((el) => { state.filters.resource = el.value; }));
  $('#filterLate').addEventListener('change', onChange((el) => { state.filters.late = el.checked; }));
  let timer = null;
  $('#filterSearch').addEventListener('input', (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.filters.q = e.target.value;
      state.caseLimit = CASE_PAGE;
      renderTracking();
    }, 180);
  });
  $('#filterReset').addEventListener('click', () => {
    state.filters = { status: '', q: '', resource: '', late: false };
    state.caseLimit = CASE_PAGE;
    $('#filterStatus').value = '';
    $('#filterResource').value = '';
    $('#filterSearch').value = '';
    $('#filterLate').checked = false;
    renderTracking();
  });
}

function filteredCases() {
  const { cases, overview } = state.data;
  void overview;
  const f = state.filters;
  const needle = f.q.trim().toLowerCase();
  return cases.filter((c) => {
    if (f.status && c.status !== f.status) return false;
    if (f.resource && !(c.resources || '').includes(f.resource)) return false;
    if (f.late && !(c.n_late > 0 || c.overdue_now)) return false;
    if (needle && !c.case_id.toLowerCase().includes(needle)) return false;
    return true;
  });
}

function renderTracking() {
  const { unit, resources } = state.data;

  const resourceSelect = $('#filterResource');
  const current = resourceSelect.value;
  resourceSelect.innerHTML = '<option value="">Mọi nguồn lực</option>' +
    resources.nodes.map((n) => `<option value="${esc(n.resource)}">${esc(n.resource)}</option>`).join('');
  resourceSelect.value = current;

  const rows = filteredCases();
  $('#caseCount').textContent = `${rows.length} / ${state.data.cases.length} ca`;

  const limit = state.caseLimit || CASE_PAGE;
  const shown = rows.slice(0, limit);

  renderTable($('#caseTable'), [
    { key: 'case_id', label: 'Ca', cls: 'mono nowrap', render: (r) => `<b>${esc(r.case_id)}</b>` },
    { key: 'status', label: 'Trạng thái', render: (r) => statusBadge(r.status) },
    {
      key: 'last_activity', label: 'Bước hiện tại',
      render: (r) => esc(activityLabel(r.last_activity)) +
        (r.overdue_now ? ' <span class="pill" style="background:#fef3f2;color:#b42318">quá hạn</span>' : ''),
    },
    {
      key: 'dwell', label: `Trong bước (${esc(unit)})`, align: 'right',
      render: (r) => `<span style="color:${r.overdue_now ? C.red : 'inherit'};font-weight:${r.overdue_now ? 700 : 400}">${fmtNum(r.dwell, 2)}</span>`,
    },
    { key: 'std_last', label: 'Định mức', align: 'right', hide: 'sm', render: (r) => fmtNum(r.std_last, 2) },
    { key: 'n_events', label: 'Số bước', align: 'right', hide: 'sm', render: (r) => fmtNum(r.n_events, 0) },
    { key: 'late_share', label: 'Tỷ lệ quá hạn', render: (r) => barCell(r.late_share, 'bad') },
    { key: 'cycle', label: `Chu kỳ (${esc(unit)})`, align: 'right', hide: 'sm', render: (r) => fmtNum(r.cycle, 1) },
    { key: 'resources', label: 'Người xử lý', hide: 'sm', render: (r) => {
      const names = String(r.resources || '').split(' · ').filter(Boolean);
      const text = names.length > 2 ? `${names.slice(0, 2).join(', ')} +${names.length - 2}` : names.join(', ');
      return `<span style="font-size:11.6px">${esc(text || '—')}</span>`;
    } },
  ], shown, {
    empty: 'Không có ca nào khớp bộ lọc',
    rowClass: () => 'clickable',
    rowAttr: (r) => `data-row="${esc(r.case_id)}"`,
    onRowClick: (caseId) => openCase(caseId),
  });

  const more = $('#caseMore');
  if (!more) return;
  if (rows.length > shown.length) {
    more.innerHTML = `<button class="btn" id="caseMoreBtn">Xem thêm ${Math.min(CASE_PAGE, rows.length - shown.length)} ca (còn ${rows.length - shown.length})</button>`;
    $('#caseMoreBtn').addEventListener('click', () => {
      state.caseLimit = (state.caseLimit || CASE_PAGE) + CASE_PAGE;
      renderTracking();
    });
  } else if (rows.length > CASE_PAGE) {
    more.innerHTML = `<span style="font-size:12px;color:var(--muted)">Đã hiển thị toàn bộ ${rows.length} ca</span>`;
  } else {
    more.innerHTML = '';
  }
}

/* ------------------------------------------------------------------ case drawer */
const roundTo = (value, digits) => Math.round(value * 10 ** digits) / 10 ** digits;

function workdaysBetween(t0, t1) {
  const start = new Date(t0);
  const end = new Date(t1);
  let day = new Date(start.getFullYear(), start.getMonth(), start.getDate());
  let total = 0;
  while (day.getTime() < end.getTime()) {
    const next = new Date(day.getFullYear(), day.getMonth(), day.getDate() + 1);
    const weekday = day.getDay();
    if (weekday >= 1 && weekday <= 5) {
      total += Math.min(end.getTime(), next.getTime()) - Math.max(start.getTime(), day.getTime());
    }
    day = next;
  }
  return total / 86400000;
}

function elapsedUnits(t0, t1, unit) {
  if (!Number.isFinite(t0) || !Number.isFinite(t1) || t1 <= t0) return 0;
  if (unit === 'phút') return (t1 - t0) / 60000;
  if (unit === 'ngày') return (t1 - t0) / 86400000;
  return workdaysBetween(t0, t1);
}

/** Dựng bảng ca từ event log tĩnh — tương đương `build_snapshot` phía Python. */
function computeCases(entry, asOfIso) {
  const src = store.events[entry.key];
  if (!src) return [];
  const asOf = Date.parse(asOfIso);
  const unit = entry.unit;
  const terminal = new Set(entry.terminal || []);
  const norms = entry.norms || {};
  const rows = src.rows;
  const acts = src.activities;
  const out = [];

  let i = 0;
  while (i < rows.length) {
    const caseIdx = rows[i][0];
    let j = i;
    const seen = [];
    while (j < rows.length && rows[j][0] === caseIdx) {
      const row = rows[j];
      if (Date.parse(row[4]) <= asOf) seen.push(row);
      j += 1;
    }
    i = j;
    if (!seen.length) continue;

    const first = seen[0];
    const last = seen[seen.length - 1];
    const lastActivity = acts[last[1]];
    const isOpen = !terminal.has(lastActivity);
    const rejected = lastActivity === 'Rejected' || lastActivity.toLowerCase().startsWith('từ chối');
    const status = isOpen ? 'Đang mở' : (rejected ? 'Bị từ chối' : 'Hoàn thành');

    const lastStart = Date.parse(last[4]);
    const lastEnd = last[5] ? Date.parse(last[5]) : null;
    let dwell = 0;
    if (isOpen) dwell = elapsedUnits(lastStart, asOf, unit);
    else if (lastActivity !== 'DONE' && lastActivity !== 'Rejected') dwell = last[6] ?? 0;

    const finish = isOpen ? asOf : (lastEnd ?? lastStart);
    const cycle = elapsedUnits(Date.parse(first[4]), finish, unit);

    let nLate = 0;
    let delayTotal = 0;
    const distinct = new Set();
    const resourceList = [];
    seen.forEach((row, index) => {
      const std = row[7];
      let duration = row[6];
      let late = row[8] === 1;
      if (index === seen.length - 1 && isOpen) {
        duration = dwell;
        late = std != null && duration > std + 1e-9;
      }
      if (late) nLate += 1;
      if (duration != null && std != null && duration > std) delayTotal += duration - std;
      distinct.add(acts[row[1]]);
      const name = src.resources[row[2]];
      if (!resourceList.includes(name)) resourceList.push(name);
    });

    const stdLast = norms[lastActivity] != null ? norms[lastActivity] : null;
    out.push({
      case_id: src.cases[caseIdx],
      status,
      is_open: isOpen,
      last_activity: lastActivity,
      last_start: last[4],
      dwell: roundTo(dwell, 2),
      std_last: stdLast == null ? null : roundTo(stdLast, 2),
      overdue_now: isOpen && stdLast != null && dwell > stdLast,
      cycle: roundTo(cycle, 2),
      n_events: seen.length,
      n_late: nLate,
      late_share: roundTo((100 * nLate) / seen.length, 1),
      delay_total: roundTo(delayTotal, 1),
      resource: resourceList[0] || '(không rõ)',
      resources: resourceList.join(' · '),
      role: src.roles[first[3]],
      rework: seen.length - distinct.size,
    });
  }

  out.sort((a, b) => (a.last_start < b.last_start ? 1 : a.last_start > b.last_start ? -1 : 0));
  out.sort((a, b) => (a.is_open ? 0 : 1) - (b.is_open ? 0 : 1));
  return out;
}

/** Dòng thời gian của một ca — tương đương `/api/case/<id>` phía Python. */
function computeCaseDetail(entry, caseId, asOfIso) {
  const src = store.events[entry.key];
  if (!src) return null;
  const caseIdx = src.cases.indexOf(caseId);
  if (caseIdx < 0) return null;
  const asOf = Date.parse(asOfIso);
  const unit = entry.unit;
  const terminal = new Set(entry.terminal || []);
  const seen = src.rows.filter((row) => row[0] === caseIdx && Date.parse(row[4]) <= asOf);
  if (!seen.length) return null;

  const lastActivity = src.activities[seen[seen.length - 1][1]];
  const isOpen = !terminal.has(lastActivity);
  const lastStartMs = Date.parse(seen[seen.length - 1][4]);

  const timeline = seen.map((row, index) => {
    const isLast = index === seen.length - 1;
    const start = Date.parse(row[4]);
    const std = row[7];
    let duration = row[6];
    let end = row[5];
    let late = row[8] === 1;
    if (isLast && isOpen) {
      duration = elapsedUnits(start, asOf, unit);
      end = null;
      late = std != null && duration > std + 1e-9;
    }
    const delay = duration != null && std != null && duration > std ? duration - std : 0;
    return {
      index: index + 1,
      activity: src.activities[row[1]],
      resource: src.resources[row[2]],
      role: src.roles[row[3]],
      start: row[4],
      end,
      duration: duration == null ? null : roundTo(duration, 2),
      std: std == null ? null : roundTo(std, 2),
      is_late: late,
      delay: roundTo(delay, 2),
      note: '',
    };
  });

  const model = entry.model || {};
  const approved = Boolean(model.approved);
  const arcs = new Set((model.arcs || []).map((arc) => `${arc[0]}\u0000${arc[1]}`));
  const transitions = [];
  for (let k = 1; k < timeline.length; k += 1) {
    const from = timeline[k - 1].activity;
    const to = timeline[k].activity;
    transitions.push({ from, to, in_model: approved ? arcs.has(`${from}\u0000${to}`) : null });
  }

  const first = timeline[0];
  const lastEnd = timeline[timeline.length - 1].end;
  const finish = isOpen ? asOf : (lastEnd ? Date.parse(lastEnd) : lastStartMs);
  const rejected = lastActivity === 'Rejected' || lastActivity.toLowerCase().startsWith('từ chối');
  return {
    case_id: caseId,
    status: isOpen ? 'Đang mở' : (rejected ? 'Bị từ chối' : 'Hoàn thành'),
    variant: timeline.map((step) => step.activity).join(' → '),
    cycle: roundTo(elapsedUnits(Date.parse(first.start), finish, unit), 2),
    unit,
    as_of: asOfIso,
    start: first.start,
    end: lastEnd,
    timeline,
    transitions,
    deviations: transitions.filter((step) => step.in_model === false),
    model_approved: approved,
  };
}

function bindDrawer() {
  $('#drawerClose').addEventListener('click', closeDrawer);
  $('#backdrop').addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });
}

function closeDrawer() {
  $('#drawer').classList.remove('show');
  $('#backdrop').classList.remove('show');
}

async function openCase(caseId) {
  const drawer = $('#drawer');
  $('#drawerTitle').textContent = caseId;
  $('#drawerSub').textContent = 'Đang tải…';
  $('#drawerBody').innerHTML = '';
  drawer.classList.add('show');
  $('#backdrop').classList.add('show');
  try {
    let detail;
    if (IS_STATIC) {
      const entry = state.sources.find((s) => s.key === state.source);
      detail = computeCaseDetail(entry, caseId, state.asOf);
      if (!detail) throw new Error(`Không thấy ca ${caseId} tại thời điểm này`);
    } else {
      const url = `/api/case/${encodeURIComponent(caseId)}?source=${encodeURIComponent(state.source)}&as_of=${encodeURIComponent(state.asOf)}`;
      detail = await api(url);
    }
    renderCaseDetail(detail);
  } catch (error) {
    $('#drawerSub').textContent = error.message;
  }
}

function renderCaseDetail(detail) {
  $('#drawerTitle').textContent = detail.case_id;
  $('#drawerSub').innerHTML =
    `${statusBadge(detail.status)} &nbsp;·&nbsp; ${fmtDateTime(detail.start)} → ${fmtDateTime(detail.end, true)}`;

  const lateSteps = detail.timeline.filter((s) => s.is_late).length;
  const body = $('#drawerBody');
  body.innerHTML = `
    <div class="detail-stats">
      <div class="detail-stat"><div class="k">Số bước</div><div class="v">${detail.timeline.length}</div></div>
      <div class="detail-stat"><div class="k">Bước quá hạn</div><div class="v" style="color:${lateSteps ? C.red : C.green}">${lateSteps}</div></div>
      <div class="detail-stat"><div class="k">Chu kỳ</div><div class="v">${fmtNum(detail.cycle, 1)} <span style="font-size:11px;color:#667085">${esc(detail.unit)}</span></div></div>
      <div class="detail-stat"><div class="k">Lệch mô hình</div><div class="v" style="color:${detail.deviations.length ? C.red : C.green}">${detail.deviations.length}</div></div>
    </div>
    <div class="card" style="margin-bottom:14px">
      <div class="card-head"><div><h3>Dòng thời gian</h3><p>Độ dài thanh = thời gian thực hiện bước (giờ)</p></div></div>
      <div class="card-body"><div id="caseGantt" class="chart" style="height:${Math.max(220, detail.timeline.length * 26 + 90)}px"></div></div>
    </div>
    <div class="card" style="margin-bottom:14px">
      <div class="card-head"><div><h3>Đường đi của ca</h3><p>Bước màu đỏ = quá hạn định mức</p></div></div>
      <div class="card-body"><div class="path-chain">${
        detail.timeline.map((s) => `<span class="step ${s.is_late ? 'late' : ''}">${esc(activityLabel(s.activity))}</span>`).join('<span class="arrow">→</span>')
      }</div></div>
    </div>
    <div class="card">
      <div class="card-head"><div><h3>Chi tiết các bước</h3><p>Thời lượng theo ${esc(detail.unit)}</p></div></div>
      <div class="card-body"><div id="caseEvents"></div></div>
    </div>`;

  renderCaseGantt(detail);
  renderTable($('#caseEvents'), [
    { key: 'index', label: '#', align: 'right', render: (r) => r.index },
    { key: 'activity', label: 'Bước', render: (r) => esc(activityLabel(r.activity)) },
    { key: 'resource', label: 'Người xử lý' },
    { key: 'role', label: 'Vai trò', render: (r) => `<span class="pill">${esc(r.role)}</span>` },
    { key: 'start', label: 'Bắt đầu', cls: 'nowrap', render: (r) => fmtDateTime(r.start) },
    { key: 'duration', label: 'Thời lượng', align: 'right', render: (r) => fmtNum(r.duration, 2) },
    { key: 'std', label: 'Định mức', align: 'right', render: (r) => fmtNum(r.std, 2) },
    { key: 'status', label: 'Đánh giá', render: (r) => (r.is_late
      ? `<span class="badge high">quá hạn +${fmtNum(r.delay, 1)}</span>`
      : '<span class="badge done">đúng hạn</span>') },
  ], detail.timeline);
}

function renderCaseGantt(detail) {
  const el = $('#caseGantt');
  if (!el) return;
  const t0 = new Date(detail.start).getTime();
  const hours = (iso) => (new Date(iso).getTime() - t0) / 3600000;

  const label = (name) => {
    const text = activityLabel(name);
    return text.length > 26 ? `${text.slice(0, 25)}…` : text;
  };

  const traces = [
    {
      type: 'bar', orientation: 'h',
      y: detail.timeline.map((s) => `#${s.index} ${label(s.activity)}`),
      x: detail.timeline.map((s) => Math.max(hours(s.end || s.start) - hours(s.start), 0.02)),
      base: detail.timeline.map((s) => hours(s.start)),
      marker: { color: detail.timeline.map((s) => (s.is_late ? C.red : C.primary)), line: { width: 0 } },
      text: detail.timeline.map((s) => fmtNum(s.duration, 1)),
      textposition: 'outside',
      textfont: { size: 10, color: '#667085' },
      hovertemplate: '<b>%{y}</b><br>Bắt đầu: %{base:.2f} h<br>Thời lượng: %{x:.2f} h<extra></extra>',
    },
  ];
  plot(el, traces, baseLayout({
    margin: { l: 200, r: 56, t: 10, b: 34 },
    barcornerradius: 3,
    xaxis: { gridcolor: C.grid, title: { text: 'Giờ kể từ khi mở ca', font: { size: 11 } }, automargin: true },
    yaxis: { automargin: true, autorange: 'reversed', tickfont: { size: 10.5 } },
  }));
}

/* ------------------------------------------------------------------ process */
function renderProcess() {
  const { process } = state.data;
  renderDfg(process);
  renderConformance(process);
  renderEdgeTable(process);
  renderVariantTable(process);
  renderDeviations(process);
}

function renderDfg(process) {
  const el = $('#chartDfg');
  if (!process.nodes.length) { emptyChart(el, 'Không có dữ liệu'); return; }

  // Sắp xếp node theo thứ tự trạng thái của quy trình (nếu biết), phần còn lại theo vị trí trung bình
  const preferred = state.data.meta.activity_order || [];
  const rank = new Map(preferred.map((name, i) => [name, i]));
  const nodes = [...process.nodes].sort((a, b) => {
    const ra = rank.has(a.id) ? rank.get(a.id) : 999 + a.order;
    const rb = rank.has(b.id) ? rank.get(b.id) : 999 + b.order;
    return ra - rb;
  });

  const remap = new Map(process.nodes.map((n, i) => [i, 0]));
  nodes.forEach((node, i) => remap.set(process.nodes.indexOf(node), i));

  const n = nodes.length;
  let nodeX;
  let nodeY;
  if (n <= 9) {
    nodeX = nodes.map((_, i) => 0.02 + (0.96 * i) / (n - 1));
    nodeY = nodes.map((node) => 0.26 + 0.48 * Math.min(1, Math.max(0, node.order)));
  } else {
    // nhiều bước: gom thành 5 cột theo vị trí trung bình, xếp dọc trong từng cột
    const slot = (node) => Math.round(Math.min(1, Math.max(0, node.order)) * 4) / 4;
    const columns = new Map();
    nodes.forEach((node) => {
      const key = slot(node);
      if (!columns.has(key)) columns.set(key, []);
      columns.get(key).push(node);
    });
    const place = new Map();
    [...columns.keys()].sort((a, b) => a - b).forEach((key) => {
      const list = columns.get(key);
      list.forEach((node, k) => {
        place.set(node.id, {
          x: 0.02 + key * 0.96,
          y: list.length === 1 ? 0.5 : 0.06 + (0.88 * (k + 0.5)) / list.length,
        });
      });
    });
    nodeX = nodes.map((node) => place.get(node.id).x);
    nodeY = nodes.map((node) => place.get(node.id).y);
  }

  const nodeColors = nodes.map((nd) =>
    nd.role === 'Supervisor' ? C.amber
      : nd.role === 'Agent' ? C.primary
        : nd.on_time_pct >= 65 ? C.primary : C.violet);
  const links = process.links.map((l) => ({ ...l, source: remap.get(l.source), target: remap.get(l.target) }));
  const linkColors = links.map((l) =>
    l.in_model ? 'rgba(79,70,229,0.22)' : 'rgba(240,68,56,0.28)');

  plot(el, [{
    type: 'sankey',
    node: {
      label: nodes.map((nd) => activityLabel(nd.id)),
      color: nodeColors,
      x: nodeX,
      y: nodeY,
      thickness: 13,
      pad: 18,
      line: { color: '#ffffff', width: 1 },
      hovertemplate: '<b>%{label}</b><br>%{value} lượt<extra></extra>',
    },
    link: {
      source: links.map((l) => l.source),
      target: links.map((l) => l.target),
      value: links.map((l) => l.value),
      color: linkColors,
      hovertemplate: '%{source.label} → %{target.label}<br>%{value} lần<extra></extra>',
    },
  }], baseLayout({ margin: { l: 16, r: 16, t: 16, b: 16 }, font: { size: 11.5 } }));
}

function renderConformance(process) {
  const conf = process.conformance;
  const host = $('#conformanceStrip');
  $('#modelSource').textContent = conf.approved
    ? `Đối chiếu với ${conf.model_label} · ${conf.model_arcs_total} luồng chuyển tiếp được định nghĩa`
    : '';
  if (!conf.approved) {
    host.innerHTML = `
      <div class="note warn" style="grid-column:1/-1">
        <span class="ico">⚠</span>
        <div><b>Bộ dữ liệu này chưa có quy trình chuẩn để đối chiếu.</b>
        Phần dưới chỉ phân tích luồng thực tế (DFG) và các biến thể — không chấm điểm tuân thủ.</div>
      </div>`;
    return;
  }
  const items = [
    { k: 'Chuyển tiếp đúng quy trình', v: `${fmtNum(conf.fit_pct, 1)}%`, h: `${conf.in_model}/${conf.transitions} lần chuyển tiếp`, tone: conf.fit_pct >= 90 ? C.green : conf.fit_pct >= 70 ? C.amber : C.red },
    { k: 'Ca đi đúng toàn bộ', v: `${fmtNum(conf.trace_fit_pct, 1)}%`, h: 'Không lệch bước nào', tone: conf.trace_fit_pct >= 60 ? C.green : C.amber },
    { k: 'Luồng lệch phát hiện', v: fmtNum(conf.deviations.length, 0), h: 'Loại chuyển tiếp ngoài quy trình', tone: conf.deviations.length ? C.red : C.green },
    { k: 'Độ phủ quy trình', v: `${fmtNum(conf.coverage_pct, 1)}%`, h: `${conf.model_arcs_covered}/${conf.model_arcs_total} bước nối trong quy trình chuẩn có xảy ra`, tone: C.primary },
  ];
  host.innerHTML = items.map((i) => `
    <div class="mini">
      <div class="k">${esc(i.k)}</div>
      <div class="v" style="color:${i.tone}">${i.v}</div>
      <div class="h">${i.h}</div>
    </div>`).join('');
}

function renderEdgeTable(process) {
  renderTable($('#edgeTable'), [
    { key: 'source', label: 'Từ bước', render: (r) => esc(activityLabel(r.source)) },
    { key: 'target', label: 'Sang bước', render: (r) => esc(activityLabel(r.target)) },
    { key: 'count', label: 'Số lần', align: 'right', render: (r) => fmtNum(r.count, 0) },
    { key: 'share', label: 'Tỷ trọng', render: (r) => barCell(r.share, 'neutral') },
    { key: 'avg_duration', label: 'Thời lượng TB', align: 'right', render: (r) => fmtNum(r.avg_duration, 2) },
    {
      key: 'in_model', label: 'Mô hình',
      render: (r) => (r.in_model ? '<span class="badge done">khớp</span>' : '<span class="badge rejected">lệch</span>'),
    },
  ], process.edges.slice(0, 20));
}

function renderVariantTable(process) {
  renderTable($('#variantTable'), [
    { key: 'short', label: 'Đường đi', render: (r) => `<span class="mono" style="font-size:11.2px;line-height:1.5">${esc(r.short)}</span>` },
    { key: 'count', label: 'Số ca', align: 'right', render: (r) => fmtNum(r.count, 0) },
    { key: 'share', label: 'Tỷ trọng', render: (r) => barCell(r.share, 'neutral') },
    { key: 'avg_cycle', label: 'Chu kỳ TB', align: 'right', render: (r) => fmtNum(r.avg_cycle, 1) },
  ], process.variants);
}

function renderDeviations(process) {
  const conf = process.conformance;
  const host = $('#deviationList');
  if (!conf.approved) {
    host.innerHTML = '<div class="empty">Không đánh giá tuân thủ cho bộ dữ liệu này.</div>';
    return;
  }
  if (!conf.deviations.length) {
    host.innerHTML = '<div class="empty">Không có cạnh nào lệch khỏi mô hình chuẩn 🎉</div>';
    return;
  }
  host.innerHTML = conf.deviations.map((d) => `
    <div class="alert-item medium">
      <div class="body">
        <div class="title">${esc(activityLabel(d.source))} → ${esc(activityLabel(d.target))}</div>
        <div class="detail">Xuất hiện ${fmtNum(d.count, 0)} lần (${fmtNum(d.share, 1)}% tổng số lần chuyển tiếp) — không có trong mô hình chuẩn.</div>
      </div>
      <span class="badge medium">${fmtNum(d.count, 0)} lần</span>
    </div>`).join('');
}

/* ------------------------------------------------------------------ resources */
function renderResources() {
  renderNetwork(state.data.resources);
  renderCentrality(state.data.resources);
  const { unit } = state.data;
  renderTable($('#resourceTable'), [
    { key: 'resource', label: 'Nguồn lực', render: (r) => `<b>${esc(r.resource)}</b>` },
    { key: 'role', label: 'Vai trò', render: (r) => `<span class="pill">${esc(r.role)}</span>` },
    { key: 'events', label: 'Số bước', align: 'right', render: (r) => fmtNum(r.events, 0) },
    { key: 'cases', label: 'Số ca', align: 'right', render: (r) => fmtNum(r.cases, 0) },
    { key: 'on_time_pct', label: 'Đúng hạn', render: (r) => barCell(r.on_time_pct) },
    { key: 'avg_duration', label: `Thời lượng TB (${esc(unit)})`, align: 'right', render: (r) => fmtNum(r.avg_duration, 2) },
    { key: 'delay', label: 'Tổng trễ', align: 'right', render: (r) => fmtNum(r.delay, 1) },
  ], state.data.resources.nodes);
}

function renderNetwork(resources) {
  const el = $('#chartNetwork');
  if (!resources.nodes.length) { emptyChart(el, 'Không có dữ liệu'); return; }
  $('#handoverHint').textContent =
    `${resources.nodes.length} nguồn lực · ${resources.n_handovers} cặp bàn giao · mũi tên chỉ chiều chuyển việc`;

  const nodes = resources.nodes;
  const n = nodes.length;
  const pos = {};
  nodes.forEach((node, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / n;
    pos[node.resource] = { x: Math.cos(angle), y: Math.sin(angle) };
  });

  const maxValue = Math.max(1, ...resources.links.map((l) => l.value));
  const arrowX = [];
  const arrowY = [];
  const arrowAngle = [];
  const groups = new Map();

  resources.links.forEach((link) => {
    const a = pos[link.source];
    const b = pos[link.target];
    if (!a || !b) return;
    const shrink = 0.12;
    const x1 = a.x + (b.x - a.x) * shrink;
    const y1 = a.y + (b.y - a.y) * shrink;
    const x2 = b.x + (a.x - b.x) * shrink;
    const y2 = b.y + (a.y - b.y) * shrink;
    if (!groups.has(link.value)) groups.set(link.value, { x: [], y: [] });
    const bucket = groups.get(link.value);
    bucket.x.push(x1, x2, null);
    bucket.y.push(y1, y2, null);

    const t = 0.82;
    arrowX.push(x1 + (x2 - x1) * t);
    arrowY.push(y1 + (y2 - y1) * t);
    arrowAngle.push((Math.atan2(x2 - x1, y2 - y1) * 180) / Math.PI);
  });

  const traces = [...groups.entries()]
    .sort((p, q) => p[0] - q[0])
    .map(([value, bucket]) => ({
      type: 'scatter',
      mode: 'lines',
      x: bucket.x,
      y: bucket.y,
      line: {
        color: 'rgba(79,70,229,0.28)',
        width: 1.4 + 3.4 * (value / maxValue),
      },
      hoverinfo: 'skip',
    }));

  traces.push({
    type: 'scatter', mode: 'markers',
    x: arrowX, y: arrowY,
    marker: { symbol: 'triangle-up', size: 7, color: 'rgba(79,70,229,0.55)', angle: arrowAngle },
    hoverinfo: 'skip',
  });

  const maxEvents = Math.max(1, ...nodes.map((nd) => nd.events));
  const dense = n > 15;
  el.style.height = `${Math.max(380, Math.min(620, 240 + n * 18))}px`;
  traces.push({
    type: 'scatter', mode: 'markers+text',
    x: nodes.map((nd) => pos[nd.resource].x),
    y: nodes.map((nd) => pos[nd.resource].y),
    text: nodes.map((nd) => nd.resource),
    textposition: nodes.map((_, i) => (pos[nodes[i].resource].y >= 0.15 ? 'top center' : 'bottom center')),
    textfont: { size: dense ? 9 : 10.5, color: '#344054' },
    marker: {
      size: nodes.map((nd) => (dense ? 11 + 18 : 16 + 30) * (nd.events / maxEvents) + (dense ? 8 : 12)),
      color: nodes.map((nd) => (nd.role === 'Supervisor' ? C.amber : nd.role === 'Agent' ? C.primary : C.cyan)),
      line: { color: '#fff', width: 2 },
      opacity: 0.92,
    },
    customdata: nodes.map((nd) => [nd.role, nd.events, nd.cases, nd.on_time_pct]),
    hovertemplate: '<b>%{text}</b><br>Vai trò: %{customdata[0]}<br>%{customdata[1]} bước · %{customdata[2]} ca<br>Đúng hạn: %{customdata[3]}%<extra></extra>',
  });

  plot(el, traces, baseLayout({
    margin: { l: 10, r: 10, t: 24, b: 10 },
    xaxis: { visible: false, range: [-1.42, 1.42], fixedrange: true },
    yaxis: { visible: false, range: [-1.32, 1.32], fixedrange: true, scaleanchor: 'x' },
    hovermode: 'closest',
  }));
}

function renderCentrality(resources) {
  const host = $('#centralityTable');
  if (!host) return;
  const rows = resources.centrality.slice(0, 12);
  if (!rows.length) { host.innerHTML = '<div class="empty">Không có dữ liệu</div>'; return; }
  const maxScore = Math.max(...rows.map((r) => r.score || 0), 0.0001);

  host.innerHTML = `<div class="rank-list">${rows.map((r, i) => `
    <div class="rank-item">
      <div class="rank-no">${i + 1}</div>
      <div class="rank-main">
        <div class="rank-name">${esc(r.resource)}
          <span class="pill">${esc(r.role)}</span></div>
        <div class="rank-bar"><div style="width:${Math.max(4, ((r.score || 0) / maxScore) * 100)}%"></div></div>
        <div class="rank-metrics">
          Degree <b>${fmtNum(r.degree, 2)}</b> · Between <b>${fmtNum(r.betweenness, 2)}</b>
          · Closeness <b>${fmtNum(r.closeness, 2)}</b> · PageRank <b>${fmtNum(r.pagerank, 3)}</b>
        </div>
      </div>
      <div class="rank-score">${fmtNum(r.score, 2)}</div>
    </div>`).join('')}</div>`;
}

/* ------------------------------------------------------------------ alerts */
function renderAlerts() {
  const payload = state.data.alerts || {};
  const alerts = payload.items || [];
  const counts = payload.counts || { high: 0, medium: 0, low: 0 };
  const total = payload.total ?? alerts.length;

  $('#navAlertCount').style.display = total ? 'inline-block' : 'none';
  $('#navAlertCount').textContent = String(total);

  $('#alertStrip').innerHTML = [
    { k: 'Nghiêm trọng', v: counts.high, tone: C.red, h: 'Cần xử lý ngay' },
    { k: 'Trung bình', v: counts.medium, tone: C.amber, h: 'Theo dõi trong tuần' },
    { k: 'Thấp', v: counts.low, tone: '#667085', h: 'Ghi nhận để cải tiến' },
    { k: 'Tổng cảnh báo', v: total, tone: C.primary, h: `Tại ${fmtDateTime(state.asOf)}` },
  ].map((i) => `
    <div class="mini"><div class="k">${esc(i.k)}</div>
      <div class="v" style="color:${i.tone}">${fmtNum(i.v, 0)}</div>
      <div class="h">${esc(i.h)}</div></div>`).join('');

  $$('#alertFilter button').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.sev === state.alertSev);
    btn.onclick = () => { state.alertSev = btn.dataset.sev; renderAlerts(); };
  });

  const list = state.alertSev ? alerts.filter((a) => a.severity === state.alertSev) : alerts;
  $('#alertCount').textContent = list.length < total
    ? `Hiển thị ${list.length} / ${total} cảnh báo (ưu tiên mức cao nhất)`
    : `${total} cảnh báo`;
  const host = $('#alertList');
  if (!list.length) {
    host.innerHTML = '<div class="empty">Không có cảnh báo ở mức này 🎉</div>';
    return;
  }
  host.innerHTML = list.map((a, index) => `
    <div class="alert-item ${esc(a.severity)}" data-index="${index}">
      <div class="body">
        <div class="title">${esc(a.title)}</div>
        <div class="detail">${esc(a.detail)}</div>
        <div class="meta">
          <span class="badge ${esc(a.severity === 'high' ? 'high' : a.severity === 'medium' ? 'medium' : 'low')}">${esc(a.severity === 'high' ? 'Nghiêm trọng' : a.severity === 'medium' ? 'Trung bình' : 'Thấp')}</span>
          <span class="pill">${esc(a.kind)}</span>
          ${a.case_id ? `<span class="pill" style="background:#eef2ff;color:#3538cd">${esc(a.case_id)}</span>` : ''}
        </div>
      </div>
    </div>`).join('');

  $$('#alertList .alert-item').forEach((el) => {
    const alert = list[Number(el.dataset.index)];
    if (alert && alert.case_id) {
      el.style.cursor = 'pointer';
      el.addEventListener('click', () => openCase(alert.case_id));
    }
  });
}

document.addEventListener('DOMContentLoaded', boot);
