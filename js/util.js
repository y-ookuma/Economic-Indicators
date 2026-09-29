// 表示用の共通関数

export const cssVar = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export const isNum = v => typeof v === 'number' && Number.isFinite(v);

export function fmt(value, decimals = 0) {
  if (!isNum(value)) return '—';
  return value.toLocaleString('ja-JP', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export function pct(v, digits = 1) {
  if (!isNum(v)) return '—';
  return `${v > 0 ? '+' : ''}${(v * 100).toFixed(digits)}%`;
}

// 比率（符号なし）
export function share(v, digits = 0) {
  return isNum(v) ? `${(v * 100).toFixed(digits)}%` : '—';
}

export function signed(v, decimals = 0) {
  if (!isNum(v)) return '—';
  return `${v > 0 ? '+' : ''}${fmt(v, decimals)}`;
}

export const signCls = v => (!isNum(v) || v === 0 ? '' : v > 0 ? 'pos' : 'neg');

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

const LEVEL = { good: ['▲', '好材料'], caution: ['▼', '注意'], info: ['●', '参考'] };

export function findingsHtml(items) {
  if (!items?.length) return '';
  return `<ul class="findings">${items.map(f => {
    const [icon, label] = LEVEL[f.level] ?? LEVEL.info;
    const ev = f.evidence ? `<span class="ev">${esc(f.evidence)}</span>` : '';
    return `<li class="${f.level}"><span class="tag">${icon} ${label}</span><span class="ft">${esc(f.text)}</span>${ev}</li>`;
  }).join('')}</ul>`;
}

export function sparkline(vals, w = 96, h = 28) {
  const v = vals.filter(isNum);
  if (v.length < 2) return '';
  const pad = 3, min = Math.min(...v), max = Math.max(...v), span = max - min || 1;
  const pts = v.map((x, i) => [pad + (i / (v.length - 1)) * (w - pad * 2), pad + (1 - (x - min) / span) * (h - pad * 2)]);
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join('');
  const last = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    <path d="${d}"/><circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2.5"/></svg>`;
}

// ホバー位置に縦線を引く Chart.js プラグイン
export const crosshair = {
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

// 折れ線グラフの共通設定。datasets: [{label, data, color, width, dash}]
export function lineChart(canvas, labels, datasets, { decimals = 2, unit = '', legend = false } = {}) {
  const muted = cssVar('--text-muted');
  const narrow = window.innerWidth < 600;
  const spanDays = labels.length > 1 ? (new Date(labels[labels.length - 1]) - new Date(labels[0])) / 86400000 : 0;
  const tickLabel = d => (spanDays > 120 ? d.slice(0, 7) : d.slice(5));
  return new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: datasets.map(d => ({
        label: d.label, data: d.data, borderColor: d.color, backgroundColor: d.color,
        borderWidth: d.width ?? 2, borderDash: d.dash ?? [], tension: 0, fill: false, spanGaps: true,
        pointRadius: d.points && labels.length <= 40 ? 3 : 0, pointHoverRadius: 4,
      })),
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: legend, labels: { color: cssVar('--text-secondary'), boxWidth: 14, boxHeight: 2 } },
        tooltip: {
          displayColors: legend,
          callbacks: { label: ctx => `${legend ? ctx.dataset.label + ': ' : ''}${fmt(ctx.parsed.y, decimals)} ${unit}` },
        },
      },
      scales: {
        x: { grid: { display: false }, border: { color: cssVar('--axis') },
             ticks: { color: muted, maxTicksLimit: narrow ? 4 : 7, maxRotation: 0,
                      callback(v) { return tickLabel(this.getLabelForValue(v)); } } },
        y: { grid: { color: cssVar('--grid') }, border: { display: false },
             ticks: { color: muted, callback: v => fmt(v, Math.min(decimals, 2)) } },
      },
    },
    plugins: [crosshair],
  });
}

export function movingAverage(vals, n) {
  const out = new Array(vals.length).fill(null);
  let sum = 0, count = 0;
  const q = [];
  vals.forEach((v, i) => {
    q.push(v);
    if (isNum(v)) { sum += v; count++; }
    if (q.length > n) { const r = q.shift(); if (isNum(r)) { sum -= r; count--; } }
    if (q.length === n && count === n) out[i] = sum / n;
  });
  return out;
}

export async function loadJson(url) {
  const res = await fetch(url, { cache: 'no-cache' });
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.json();
}
