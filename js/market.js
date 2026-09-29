// 「市場」タブ：指標タイルと詳細グラフ
import { cssVar, esc, fmt, lineChart, sparkline } from './util.js';

const MIN_POINTS = 12;         // 月次・四半期データでも最低この点数は表示する
const SPARK_POINTS = { daily: 60, other: 24 };

let DATA = null;
let selectedKey = null;
let rangeDays = 365;
let chart = null;

function isDaily(s) {
  const h = s.history;
  if (h.length < 3) return false;
  return (new Date(h[h.length - 1][0]) - new Date(h[h.length - 3][0])) / 86400000 <= 10;
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

function renderGroups() {
  const root = document.getElementById('groups');
  root.innerHTML = DATA.groups.map(g => {
    const tiles = g.items.filter(k => DATA.series[k]).map(k => {
      const s = DATA.series[k];
      const d = deltaInfo(s);
      const n = isDaily(s) ? SPARK_POINTS.daily : SPARK_POINTS.other;
      const stale = s.stale ? ' <span class="stale" title="最新の取得に失敗したため前回データを表示">⚠ 未更新</span>' : '';
      return `<button type="button" class="tile" data-key="${k}" title="${esc(s.note ?? '')}">
        <span class="tile-label">${esc(s.name)}</span>
        <span class="tile-value">${fmt(s.latest.value, s.decimals)}<span class="unit">${esc(s.unit)}</span></span>
        <span class="tile-delta ${d.cls}">${d.text}</span>
        <span class="tile-foot">
          <span class="tile-date">${s.latest.date}${stale}</span>
          ${sparkline(s.history.slice(-n).map(p => p[1]))}
        </span>
      </button>`;
    }).join('');
    return `<section class="group"><h2>${esc(g.name)}</h2><div class="tiles">${tiles}</div></section>`;
  }).join('');
  root.querySelectorAll('.tile').forEach(el => el.addEventListener('click', () => select(el.dataset.key, true)));
}

function visibleHistory(s) {
  const h = s.history;
  if (!rangeDays) return h;
  const cutoff = new Date(h[h.length - 1][0]);
  cutoff.setDate(cutoff.getDate() - rangeDays);
  const iso = cutoff.toISOString().slice(0, 10);
  const filtered = h.filter(p => p[0] >= iso);
  return filtered.length >= MIN_POINTS ? filtered : h.slice(-MIN_POINTS);
}

export function render() {
  if (!DATA || !selectedKey) return;
  const s = DATA.series[selectedKey];
  const hist = visibleHistory(s);

  document.getElementById('detailTitle').textContent = s.name;
  const src = s.source === 'yfinance' ? `Yahoo Finance ${s.ticker}` : `FRED ${s.series_id}`;
  document.getElementById('detailMeta').textContent =
    `${fmt(s.latest.value, s.decimals)}${s.unit}（${s.latest.date}）・出典: ${src}${s.note ? '・' + s.note : ''}`;
  document.querySelector('#detailTable tbody').innerHTML = s.history.slice(-20).reverse()
    .map(p => `<tr><td>${p[0]}</td><td>${fmt(p[1], s.decimals)}</td></tr>`).join('');

  if (chart) chart.destroy();
  chart = lineChart(document.getElementById('detailChart'), hist.map(p => p[0]),
    [{ label: s.name, data: hist.map(p => p[1]), color: cssVar('--series-1'), points: true }],
    { decimals: s.decimals, unit: s.unit });
}

function select(key, scroll) {
  selectedKey = key;
  document.querySelectorAll('.tile').forEach(el => el.classList.toggle('selected', el.dataset.key === key));
  history.replaceState(null, '', `#market/${key}`);
  render();
  if (scroll) document.getElementById('detail').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

export function init(data, initialKey) {
  DATA = data;
  document.querySelectorAll('#marketRanges button').forEach(b => b.addEventListener('click', () => {
    rangeDays = Number(b.dataset.range);
    document.querySelectorAll('#marketRanges button').forEach(x => x.classList.toggle('active', x === b));
    render();
  }));
  const errs = Object.keys(DATA.errors || {});
  if (errs.length) {
    const el = document.getElementById('errors');
    el.hidden = false;
    el.textContent = `取得に失敗した指標: ${errs.join(', ')}（前回データを表示）`;
  }
  renderGroups();
  selectedKey = DATA.series[initialKey] ? initialKey : DATA.groups[0].items[0];
  document.querySelectorAll('.tile').forEach(el => el.classList.toggle('selected', el.dataset.key === selectedKey));
}
