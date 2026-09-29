// 「農業・先物」タブ：エネルギー・穀物先物をドル建てと円換算で比較する
import { cssVar, esc, findingsHtml, fmt, lineChart, pct, signCls, sparkline } from './util.js';

let IND = null;        // data/indicators.json
let ANALYSIS = null;   // data/analysis.json
let selected = 'heating_oil';
let currency = 'yen';  // 'usd' | 'yen'
let rangeDays = 365;
let chart = null;

// ドル建て価格 × その日（なければ直前）のドル円
function yenSeries(hist) {
  const fx = IND.series.usdjpy.history;
  let j = 0, rate = null;
  return hist.map(([d, v]) => {
    while (j < fx.length && fx[j][0] <= d) rate = fx[j++][1];
    return [d, rate == null ? null : v * rate];
  }).filter(p => p[1] != null);
}

function drawChart() {
  const s = IND.series[selected];
  let hist = currency === 'yen' ? yenSeries(s.history) : s.history;
  if (rangeDays) {
    const cutoff = new Date(hist[hist.length - 1][0]);
    cutoff.setDate(cutoff.getDate() - rangeDays);
    const iso = cutoff.toISOString().slice(0, 10);
    hist = hist.filter(p => p[0] >= iso);
  }
  const unit = currency === 'yen' ? `円/${s.unit.split('/')[1] ?? ''}` : s.unit;
  document.getElementById('futTitle').textContent = `${s.name}（${currency === 'yen' ? '円換算' : 'ドル建て'}）`;
  document.getElementById('futMeta').textContent =
    `${s.note ? s.note + '・' : ''}出典: Yahoo Finance ${s.ticker}${currency === 'yen' ? ' × ドル円' : ''}`;
  if (chart) chart.destroy();
  chart = lineChart(document.getElementById('futChart'), hist.map(p => p[0]),
    [{ label: s.name, data: hist.map(p => p[1]), color: cssVar('--series-1') }],
    { decimals: currency === 'yen' ? (s.unit.startsWith('セント') ? 0 : 1) : s.decimals, unit });
}

function toggleActive(sel, attr, value) {
  document.querySelectorAll(sel).forEach(b => b.classList.toggle('active', b.dataset[attr] === String(value)));
}

function render() {
  const rows = ANALYSIS.commodities.map(c => `
    <tr data-key="${c.key}" tabindex="0" class="${c.key === selected ? 'selected' : ''}">
      <td>${esc(c.name)}<br><small>${esc(c.unit)}・${c.date}</small></td>
      <td>${fmt(c.price, c.decimals)}</td>
      <td>${sparkline(IND.series[c.key].history.slice(-120).map(p => p[1]), 100, 24)}</td>
      ${['usd_1m', 'usd_3m', 'usd_1y', 'yen_1m', 'yen_3m', 'yen_1y'].map(k => `<td class="${signCls(c[k])}">${pct(c[k])}</td>`).join('')}
    </tr>`).join('');

  document.getElementById('futuresBody').innerHTML = `
    <section class="panel">
      <h2 class="panel-title">コストへの影響（円換算）</h2>
      ${findingsHtml(ANALYSIS.commodity_findings)}
      <p class="sub">色分けは農業経営のコストの視点です（燃料・肥料原料の上昇＝注意）。円換算＝ドル建て価格×ドル円で、輸入コストの実感に近い値です。</p>
    </section>
    <section class="detail">
      <div class="detail-head">
        <div><h2 id="futTitle">—</h2><p class="detail-meta" id="futMeta"></p></div>
        <div class="ranges-wrap">
          <div class="ranges" role="group" aria-label="通貨">
            <button type="button" data-cur="yen">円換算</button>
            <button type="button" data-cur="usd">ドル建て</button>
          </div>
          <div class="ranges" role="group" aria-label="表示期間">
            <button type="button" data-range="90">3M</button>
            <button type="button" data-range="365">1Y</button>
            <button type="button" data-range="1825">5Y</button>
          </div>
        </div>
      </div>
      <div class="chart-wrap"><canvas id="futChart" role="img" aria-label="選択中の先物の推移"></canvas></div>
    </section>
    <section class="panel table-wrap">
      <table class="fut-table">
        <thead><tr><th>品目 <small>行をクリックでグラフ表示</small></th><th>価格</th><th>推移(約半年)</th>
          <th>1か月<br><small>ドル建</small></th><th>3か月<br><small>ドル建</small></th><th>1年<br><small>ドル建</small></th>
          <th>1か月<br><small>円換算</small></th><th>3か月<br><small>円換算</small></th><th>1年<br><small>円換算</small></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </section>`;

  document.querySelectorAll('.fut-table tr[data-key]').forEach(tr => {
    const go = () => {
      selected = tr.dataset.key;
      document.querySelectorAll('.fut-table tr[data-key]').forEach(x => x.classList.toggle('selected', x === tr));
      drawChart();
    };
    tr.addEventListener('click', go);
    tr.addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
  });
  document.querySelectorAll('#futuresBody [data-cur]').forEach(b => b.addEventListener('click', () => {
    currency = b.dataset.cur; toggleActive('#futuresBody [data-cur]', 'cur', currency); drawChart();
  }));
  document.querySelectorAll('#futuresBody [data-range]').forEach(b => b.addEventListener('click', () => {
    rangeDays = Number(b.dataset.range); toggleActive('#futuresBody [data-range]', 'range', rangeDays); drawChart();
  }));
  toggleActive('#futuresBody [data-cur]', 'cur', currency);
  toggleActive('#futuresBody [data-range]', 'range', rangeDays);
  drawChart();
}

export function show(ind, analysis) {
  IND = ind;
  ANALYSIS = analysis;
  if (!IND.series[selected]) selected = ANALYSIS.commodities[0]?.key;
  render();
}

export function rerender() {
  if (IND && ANALYSIS && document.getElementById('futChart')) drawChart();
}
