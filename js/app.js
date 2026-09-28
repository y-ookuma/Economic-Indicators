// Economic Indicators ダッシュボード
// data/indicators.json（GitHub Actions が定期生成）を読み込んで表示する。

const DATA_URL = 'data/indicators.json';
const MIN_POINTS = 12;         // 月次・四半期データでも最低この点数は表示する
const SPARK_POINTS = { daily: 60, other: 24 };

let DATA = null;
let selectedKey = null;
let rangeDays = 365;
let chart = null;

// ---------- 表示用ユーティリティ ----------
const cssVar = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function fmt(value, decimals) {
  return value.toLocaleString('ja-JP', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function isDaily(s) {
  const h = s.history;
  if (h.length < 3) return false;
  const days = (new Date(h[h.length - 1][0]) - new Date(h[h.length - 3][0])) / 86400000;
  return days <= 10;
}

// 前回比。単位が % の指標は差（pt）、それ以外は差（水準値なら変化率も）を表示する
function deltaInfo(s) {
  const c = s.change;
  if (!c) return { text: '—', cls: '' };
  const arrow = c.abs > 0 ? '▲' : c.abs < 0 ? '▼' : '―';
  const sign = c.abs > 0 ? '+' : '';
  let text;
  if (s.unit === '%') {
    text = `${arrow} ${sign}${fmt(c.abs, Math.max(s.decimals, 2))}pt`;
  } else {
    text = `${arrow} ${sign}${fmt(c.abs, s.decimals)}`;
    // 前期差などの加工値に変化率は意味がないので、生の水準値のときだけ出す
    if (c.pct != null && !s.transform) text += `（${sign}${fmt(c.pct, 2)}%）`;
  }
  let cls = '';
  if (s.polarity && c.abs !== 0) cls = (c.abs > 0) === (s.polarity > 0) ? 'good' : 'bad';
  return { text, cls };
}

function sparkline(history) {
  const w = 96, h = 28, pad = 3;
  const vals = history.map(p => p[1]);
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  const pts = vals.map((v, i) => [
    pad + (i / Math.max(vals.length - 1, 1)) * (w - pad * 2),
    pad + (1 - (v - min) / span) * (h - pad * 2),
  ]);
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join('');
  const last = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    <path d="${d}"/><circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2.5"/></svg>`;
}

// ---------- タイル ----------
function renderGroups() {
  const root = document.getElementById('groups');
  root.innerHTML = DATA.groups.map(g => {
    const tiles = g.items.filter(k => DATA.series[k]).map(k => {
      const s = DATA.series[k];
      const d = deltaInfo(s);
      const n = isDaily(s) ? SPARK_POINTS.daily : SPARK_POINTS.other;
      const stale = s.stale ? ' <span class="stale" title="最新の取得に失敗したため前回データを表示">⚠ 未更新</span>' : '';
      return `<button type="button" class="tile" data-key="${k}" title="${s.note ?? ''}">
        <span class="tile-label">${s.name}</span>
        <span class="tile-value">${fmt(s.latest.value, s.decimals)}<span class="unit">${s.unit}</span></span>
        <span class="tile-delta ${d.cls}">${d.text}</span>
        <span class="tile-foot">
          <span class="tile-date">${s.latest.date}${stale}</span>
          ${sparkline(s.history.slice(-n))}
        </span>
      </button>`;
    }).join('');
    return `<section class="group"><h2>${g.name}</h2><div class="tiles">${tiles}</div></section>`;
  }).join('');

  root.querySelectorAll('.tile').forEach(el =>
    el.addEventListener('click', () => select(el.dataset.key, true)));
}

// ---------- 詳細グラフ ----------
function visibleHistory(s) {
  const h = s.history;
  if (!rangeDays) return h;
  const cutoff = new Date(h[h.length - 1][0]);
  cutoff.setDate(cutoff.getDate() - rangeDays);
  const iso = cutoff.toISOString().slice(0, 10);
  const filtered = h.filter(p => p[0] >= iso);
  return filtered.length >= MIN_POINTS ? filtered : h.slice(-MIN_POINTS);
}

// ホバー位置に縦線を引くプラグイン
const crosshair = {
  id: 'crosshair',
  afterDraw(c) {
    const active = c.tooltip?.getActiveElements?.();
    if (!active?.length) return;
    const x = active[0].element.x;
    const { top, bottom } = c.chartArea;
    c.ctx.save();
    c.ctx.strokeStyle = cssVar('--axis');
    c.ctx.lineWidth = 1;
    c.ctx.beginPath(); c.ctx.moveTo(x, top); c.ctx.lineTo(x, bottom); c.ctx.stroke();
    c.ctx.restore();
  },
};

function renderChart() {
  const s = DATA.series[selectedKey];
  const hist = visibleHistory(s);
  const accent = cssVar('--accent'), grid = cssVar('--grid'), muted = cssVar('--text-muted');
  const narrow = window.innerWidth < 600;
  // 長い期間は年月だけ表示して目盛りを重ならせない
  const spanDays = (new Date(hist[hist.length - 1][0]) - new Date(hist[0][0])) / 86400000;
  const tickLabel = d => spanDays > 120 ? d.slice(0, 7) : d.slice(5);

  document.getElementById('detailTitle').textContent = s.name;
  const src = s.source === 'yfinance' ? `Yahoo Finance ${s.ticker}` : `FRED ${s.series_id}`;
  document.getElementById('detailMeta').textContent =
    `${fmt(s.latest.value, s.decimals)}${s.unit}（${s.latest.date}）・出典: ${src}${s.note ? '・' + s.note : ''}`;

  document.querySelector('#detailTable tbody').innerHTML = s.history.slice(-20).reverse()
    .map(p => `<tr><td>${p[0]}</td><td>${fmt(p[1], s.decimals)}</td></tr>`).join('');

  const config = {
    type: 'line',
    data: {
      labels: hist.map(p => p[0]),
      datasets: [{
        label: s.name, data: hist.map(p => p[1]),
        borderColor: accent, borderWidth: 2, pointRadius: hist.length <= 40 ? 3 : 0,
        pointBackgroundColor: accent, pointHoverRadius: 5, tension: 0, fill: false,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          displayColors: false,
          callbacks: { label: ctx => `${fmt(ctx.parsed.y, s.decimals)} ${s.unit}` },
        },
      },
      scales: {
        x: { grid: { display: false }, border: { color: cssVar('--axis') },
             ticks: { color: muted, maxTicksLimit: narrow ? 4 : 7, maxRotation: 0,
                      callback(v) { return tickLabel(this.getLabelForValue(v)); } } },
        y: { grid: { color: grid }, border: { display: false },
             ticks: { color: muted, callback: v => fmt(v, Math.min(s.decimals, 2)) } },
      },
    },
    plugins: [crosshair],
  };
  if (chart) chart.destroy();
  chart = new Chart(document.getElementById('detailChart'), config);
}

function select(key, scroll) {
  selectedKey = key;
  document.querySelectorAll('.tile').forEach(el => el.classList.toggle('selected', el.dataset.key === key));
  history.replaceState(null, '', '#' + key);
  renderChart();
  if (scroll) document.getElementById('detail').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ---------- テーマ ----------
function applyTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
  if (chart) renderChart();
}

function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem('theme'); } catch (e) { /* 保存不可の環境 */ }
  applyTheme(saved);
  document.getElementById('themeToggle').addEventListener('click', () => {
    const dark = document.documentElement.dataset.theme === 'dark' ||
      (!document.documentElement.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
    const next = dark ? 'light' : 'dark';
    try { localStorage.setItem('theme', next); } catch (e) { /* 無視 */ }
    applyTheme(next);
  });
}

// ---------- 起動 ----------
async function main() {
  initTheme();
  document.querySelectorAll('.ranges button').forEach(b => b.addEventListener('click', () => {
    rangeDays = Number(b.dataset.range);
    document.querySelectorAll('.ranges button').forEach(x => x.classList.toggle('active', x === b));
    renderChart();
  }));

  try {
    const res = await fetch(DATA_URL, { cache: 'no-cache' });
    if (!res.ok) throw new Error(res.status);
    DATA = await res.json();
  } catch (e) {
    document.getElementById('updated').textContent = `データを読み込めませんでした（${e.message}）`;
    return;
  }

  const t = new Date(DATA.updated_at);
  document.getElementById('updated').textContent =
    `最終更新: ${t.toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })} JST`;

  const errs = Object.keys(DATA.errors || {});
  if (errs.length) {
    const el = document.getElementById('errors');
    el.hidden = false;
    el.textContent = `取得に失敗した指標: ${errs.join(', ')}（前回データを表示）`;
  }

  renderGroups();
  const fromHash = location.hash.slice(1);
  select(DATA.series[fromHash] ? fromHash : DATA.groups[0].items[0], false);
}

main();
