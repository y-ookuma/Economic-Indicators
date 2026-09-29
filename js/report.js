// 「保有株レポート」タブ
// 保有 JSON はブラウザ内だけで処理する（送信しない）。銘柄ごとの指標・判定は data/stocks.json（Actions で計算済み）を使い、
// 損益・比率・ポートフォリオ全体の判定だけをここで計算する。
import { cssVar, esc, findingsHtml, fmt, isNum, lineChart, loadJson, movingAverage, pct, share, signCls, signed } from './util.js';

const STORAGE_KEY = 'holdings.v1';
const WEIGHT_ALERT = 0.30;     // 1銘柄の比率
const LOSS_ALERT = -0.20;      // 含み損率
const SECTOR_ALERT = 0.40;     // 1業種の比率
const CHART_DAYS = 245;

let STOCKS = null;       // data/stocks.json
let ANALYSIS = null;     // data/analysis.json
let holdings = null;     // { source, isSample, items: [...] }
let subTab = 'summary';
let charts = [];
let cardsRendered = false;

// ---------- 保有 JSON ----------
function validate(json) {
  const list = Array.isArray(json) ? json : json?.holdings;
  if (!Array.isArray(list) || !list.length) throw new Error('"holdings" の配列が見つかりません');
  return list.map((h, i) => {
    const code = String(h.code ?? '').trim().toUpperCase();
    const shares = Number(h.shares), cost = Number(h.avg_cost);
    if (!code) throw new Error(`${i + 1}件目: code（証券コード）がありません`);
    if (!(shares > 0)) throw new Error(`${i + 1}件目（${code}）: shares（株数）は正の数で指定してください`);
    if (!(cost >= 0)) throw new Error(`${i + 1}件目（${code}）: avg_cost（平均取得単価）は数値で指定してください`);
    return { code, name: h.name ? String(h.name) : '', shares, avg_cost: cost, memo: h.memo ? String(h.memo) : '' };
  });
}

function save() {
  try {
    if (document.getElementById('rememberHoldings').checked && holdings && !holdings.isSample) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(holdings));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  } catch (e) { /* 保存できない環境では何もしない */ }
}

function restore() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) holdings = JSON.parse(raw);
  } catch (e) { holdings = null; }
}

async function readFile(file) {
  try {
    const items = validate(JSON.parse(await file.text()));
    holdings = { source: file.name, isSample: false, items };
    save();
    render();
  } catch (e) {
    showLoaderError(`読み込めませんでした: ${e.message}`);
  }
}

function showLoaderError(msg) {
  let el = document.getElementById('loaderError');
  if (!el) {
    el = document.createElement('p');
    el.id = 'loaderError';
    el.className = 'errors';
    document.getElementById('dropzone').after(el);
  }
  el.textContent = msg;
}

// ---------- 計算 ----------
function enrich() {
  const rows = holdings.items.map(h => {
    const s = STOCKS.stocks[h.code];
    if (!s) return { ...h, missing: true };
    const value = s.price * h.shares;
    const pnl = (s.price - h.avg_cost) * h.shares;
    return { ...h, s, name: h.name || s.name, value, pnl, pnlPct: h.avg_cost ? s.price / h.avg_cost - 1 : NaN };
  });
  const ok = rows.filter(r => !r.missing);
  const total = ok.reduce((a, r) => a + r.value, 0);
  ok.forEach(r => { r.weight = total ? r.value / total : 0; });
  return { rows, ok, total, pnl: ok.reduce((a, r) => a + r.pnl, 0) };
}

function portfolioFindings({ ok, total }) {
  const out = [];
  if (!total) return out;
  const t = ANALYSIS.thresholds;
  ok.filter(r => r.weight >= WEIGHT_ALERT).forEach(r => out.push({
    level: 'caution', text: `${r.name} が評価額の ${share(r.weight)} を占める（集中）`, evidence: `${share(WEIGHT_ALERT)} 以上で表示` }));

  const sectors = sectorBreakdown(ok);
  const top = sectors[0];
  if (top && top.weight >= SECTOR_ALERT && ok.length > 1) out.push({
    level: 'caution', text: `業種「${top.sector}」が評価額の ${share(top.weight)} を占める`, evidence: `${share(SECTOR_ALERT)} 以上で表示。同じ業種は同じ材料で一緒に動きやすい` });

  const withBeta = ok.filter(r => isNum(r.s.metrics.beta));
  if (withBeta.length) {
    const w = withBeta.reduce((a, r) => a + r.weight, 0);
    const pb = withBeta.reduce((a, r) => a + r.s.metrics.beta * r.weight, 0) / w;
    out.push({ level: 'info', text: `ポートフォリオ全体の日経平均β ≒ ${pb.toFixed(2)}`,
      evidence: `日経平均が 10% 下落すると、評価額は単純計算で約 ${(pb * 10).toFixed(0)}%（${fmt(total * pb * 0.1)} 円）減る` });
  }
  const fx = ok.filter(r => Math.abs(r.s.metrics.fx_t ?? 0) >= t.t_significant);
  if (fx.length) {
    const pf = fx.reduce((a, r) => a + r.s.metrics.fx_beta * r.weight, 0);
    if (Math.abs(pf) >= 0.01) out.push({ level: 'info', text: `為替感応度が有意な銘柄の合計寄与 ${signed(pf, 2)}`,
      evidence: `ドル円が 5% 円高になると、評価額は約 ${signed(-pf * 5, 1)}% 変わる（日経平均一定の場合）` });
  }
  return out;
}

function sectorBreakdown(ok) {
  const m = new Map();
  ok.forEach(r => m.set(r.s.sector || 'その他', (m.get(r.s.sector || 'その他') || 0) + r.weight));
  return [...m].map(([sector, weight]) => ({ sector, weight })).sort((a, b) => b.weight - a.weight);
}

function holdingFindings(r) {
  const f = [...r.s.findings];
  if (isNum(r.pnlPct) && r.pnlPct <= LOSS_ALERT) {
    f.push({ level: 'caution', text: `含み損 ${pct(r.pnlPct, 0)}：購入時の理由が今も成り立つか再確認を` });
  }
  return f;
}

const scoreLabel = s => (s >= 2 ? '追い風が多い' : s <= -2 ? '逆風が多い' : '材料が混在');
const scoreCls = s => `s${Math.max(-3, Math.min(3, s))}`;

// ---------- 描画 ----------
function summaryHtml(p) {
  const cost = p.total - p.pnl;
  const missing = p.rows.filter(r => r.missing);
  const rows = p.ok.map(r => `
    <tr data-code="${esc(r.code)}" tabindex="0">
      <td>${esc(r.name)}<br><small>${esc(r.code)}・${esc(r.s.sector ?? '')}</small></td>
      <td>${fmt(r.shares)}</td><td>${fmt(r.s.price, 1)}</td><td>${fmt(r.value)}</td><td>${share(r.weight)}</td>
      <td class="${signCls(r.pnl)}">${signed(r.pnl)}<br><small>${pct(r.pnlPct)}</small></td>
      <td class="${signCls(r.s.metrics.ret_1m)}">${pct(r.s.metrics.ret_1m)}</td>
      <td><span class="chip ${scoreCls(r.s.score)}">${signed(r.s.score)}</span> ${scoreLabel(r.s.score)}</td>
    </tr>`).join('');
  const sectors = sectorBreakdown(p.ok).map(x => `
    <div class="bar-row"><span class="bar-label">${esc(x.sector)}</span>
      <span class="bar"><span style="width:${(x.weight * 100).toFixed(1)}%"></span></span>
      <span class="bar-value">${share(x.weight)}</span></div>`).join('');
  const missingHtml = missing.length ? `<p class="banner">分析データがない銘柄: ${missing.map(r => esc(r.code)).join(', ')}。
    東証プライム・ETF 以外の銘柄は <code>config/watchlist.json</code> に追加してください（次回の自動更新から分析されます）。</p>` : '';

  return `
    ${missingHtml}
    <section class="panel">
      <div class="hero">
        <div><div class="lbl">評価額</div><div class="big">${fmt(p.total)} 円</div></div>
        <div><div class="lbl">含み損益</div><div class="big sub-big ${signCls(p.pnl)}">${signed(p.pnl)} 円 <small>${pct(cost ? p.pnl / cost : NaN)}</small></div></div>
      </div>
      <div class="two-col">
        <div><h3>市場環境（日本株中心）</h3>${findingsHtml(ANALYSIS.market)}</div>
        <div><h3>ポートフォリオ全体</h3>${findingsHtml(portfolioFindings(p))}
          <h3>業種別の比率</h3><div class="bars">${sectors}</div></div>
      </div>
    </section>
    <h3 class="section-title">保有銘柄一覧 <small>行をクリックすると銘柄別分析へ</small></h3>
    <section class="panel table-wrap"><table class="holdings-table">
      <thead><tr><th>銘柄</th><th>株数</th><th>株価</th><th>評価額</th><th>比率</th><th>損益</th><th>1か月</th><th>環境スコア</th></tr></thead>
      <tbody>${rows}</tbody></table></section>`;
}

function stockCard(code, s, h) {
  const m = s.metrics;
  const own = h ? [
    ['損益', `${signed(h.pnl)} 円（${pct(h.pnlPct)}）`, signCls(h.pnl)],
    ['取得単価', `${fmt(h.avg_cost, 1)} 円 × ${fmt(h.shares)}株`, ''],
  ] : [];
  const stats = [
    ['株価', `${fmt(s.price, 1)} 円`, ''], ...own,
    ['1か月', pct(m.ret_1m), signCls(m.ret_1m)], ['3か月', pct(m.ret_3m), signCls(m.ret_3m)],
    ['1年', pct(m.ret_1y), signCls(m.ret_1y)], ['対日経(3か月)', pct(m.rel_3m), signCls(m.rel_3m)],
    ['RSI(14)', fmt(m.rsi), ''], ['25日線乖離', pct(m.dev25), ''],
    ['日経β', fmt(m.beta, 2), ''], ['為替感応度', `${signed(m.fx_beta, 2)}（t=${fmt(m.fx_t, 1)}）`, ''],
    ['年率ボラ', pct(m.vol, 0).replace('+', ''), ''], ['52週高値比', pct(m.dd_52w), ''],
  ].map(([k, v, c]) => `<div><dt>${k}</dt><dd class="${c}">${v}</dd></div>`).join('');
  const memo = h?.memo ? `<p class="memo">メモ: ${esc(h.memo)}</p>` : '';
  const findings = h ? holdingFindings(h) : s.findings;
  return `
    <article class="card" id="card-${esc(code)}">
      <div class="card-head">
        <h3>${esc(h?.name || s.name)} <small>${esc(code)}・${esc(s.sector ?? '')}・${s.date}</small></h3>
        <div class="score ${scoreCls(s.score)}"><b>${signed(s.score)}</b> ${scoreLabel(s.score)}
          <span>${esc(s.score_parts.join('、'))}</span></div>
      </div>
      ${memo}
      <div class="card-body">
        <div class="chart"><canvas data-code="${esc(code)}" role="img" aria-label="${esc(s.name)} の株価と移動平均（1年）"></canvas></div>
        <dl class="stats">${stats}</dl>
      </div>
      ${findingsHtml(findings)}
    </article>`;
}

const priceCache = new Map();
const loadPrices = code => {
  if (!priceCache.has(code)) priceCache.set(code, loadJson(`data/prices/${encodeURIComponent(code)}.json`));
  return priceCache.get(code);
};

// 株価は銘柄ごとのファイル（data/prices/{code}.json）を表示する分だけ取得する
function drawCardCharts(root, costs = {}) {
  root.querySelectorAll('canvas[data-code]').forEach(async cv => {
    const code = cv.dataset.code;
    let raw;
    try {
      raw = await loadPrices(code);
    } catch (e) {
      cv.parentElement.innerHTML = `<p class="errors">株価データを読み込めませんでした（${esc(e.message)}）</p>`;
      return;
    }
    if (!cv.isConnected) return;   // 読み込み中に画面が切り替わった
    // 休場などの欠損は直前の値で埋めてから移動平均を計算する
    let last = null;
    const close = raw.map(v => (v == null ? last : (last = v)));
    const ma25 = movingAverage(close, 25), ma75 = movingAverage(close, 75);
    const from = Math.max(0, close.length - CHART_DAYS);
    const labels = STOCKS.dates.slice(from);
    const sets = [
      { label: '株価', data: close.slice(from), color: cssVar('--series-1') },
      { label: '25日線', data: ma25.slice(from), color: cssVar('--series-2'), width: 1.5 },
      { label: '75日線', data: ma75.slice(from), color: cssVar('--series-3'), width: 1.5 },
    ];
    if (costs[code] != null) sets.push({ label: '取得単価', data: labels.map(() => costs[code]), color: cssVar('--text-muted'), width: 1, dash: [4, 4] });
    charts.push(lineChart(cv, labels, sets, { decimals: 1, unit: '円', legend: true }));
  });
}

function clearCharts() {
  charts.forEach(c => c.destroy());
  charts = [];
}

function renderSub() {
  document.querySelectorAll('.subtabs button').forEach(b => {
    const on = b.dataset.sub === subTab;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', on);
  });
  document.querySelectorAll('.subpanel').forEach(p => { p.hidden = p.dataset.sub !== subTab; });
  if (subTab === 'cards' && !cardsRendered) {
    const p = enrich();
    const root = document.querySelector('.subpanel[data-sub="cards"]');
    root.innerHTML = p.ok.map(r => stockCard(r.code, r.s, r)).join('') || '<p>分析できる銘柄がありません。</p>';
    drawCardCharts(root, Object.fromEntries(p.ok.map(r => [r.code, r.avg_cost])));
    cardsRendered = true;
  }
}

function searchHtml() {
  const opts = Object.entries(STOCKS.stocks)
    .map(([c, s]) => `<option value="${esc(c)} ${esc(s.name)}"></option>`).join('');
  return `
    <section class="panel">
      <label for="stockSearch">証券コードまたは銘柄名（${Object.keys(STOCKS.stocks).length.toLocaleString()}銘柄）</label>
      <input id="stockSearch" list="stockList" placeholder="例: 7203 / トヨタ" autocomplete="off">
      <datalist id="stockList">${opts}</datalist>
      <p class="sub">${esc(STOCKS.universe_source)}。保有していない銘柄の状態確認に使えます。</p>
    </section>
    <div id="searchResult"></div>`;
}

function rulesHtml() {
  const t = ANALYSIS.thresholds;
  return `<section class="panel rules"><ul>
    <li><b>環境スコア</b>＝銘柄のトレンド（±1）＋日経平均のトレンド（±1）＋為替の追い風・逆風（±1、感応度が有意な銘柄のみ）−過熱（1）。売買の推奨ではなく、材料の向きを数えたもの。<b>このスコアとその後のリターンの関係はまだ検証していない。</b></li>
    <li><b>トレンド</b>：株価＞25日線＞75日線 かつ 75日線が上向き＝上昇、逆の並びかつ下向き＝下降、それ以外＝もみ合い。</li>
    <li><b>過熱・売られすぎ</b>：RSI(14) ≥ ${t.rsi_hot} または 25日線乖離 ≥ ${pct(t.dev25_hot, 0)}／RSI ≤ ${t.rsi_cold} または乖離 ≤ ${pct(t.dev25_cold, 0)}。</li>
    <li><b>日経β・為替感応度</b>：直近1年の日次対数収益率を「日経平均」と「ドル円」で重回帰した係数。|t| ≥ ${t.t_significant} のときだけ為替の影響を判定に使う。</li>
    <li><b>ポートフォリオ</b>：1銘柄 ${share(WEIGHT_ALERT)} 以上、1業種 ${share(SECTOR_ALERT)} 以上で集中の注意、含み損 ${pct(LOSS_ALERT, 0)} 以下で見直しの注意。</li>
    <li>閾値は <code>scripts/analysis.py</code>（銘柄の判定）と <code>js/report.js</code>（ポートフォリオの判定）の先頭で変更できる。</li>
  </ul></section>`;
}

function render() {
  clearCharts();
  cardsRendered = false;
  const loader = document.getElementById('reportLoader');
  const body = document.getElementById('reportBody');
  if (!holdings) {
    loader.hidden = false;
    body.hidden = true;
    return;
  }
  loader.hidden = true;
  body.hidden = false;
  const p = enrich();
  body.innerHTML = `
    <div class="report-bar">
      <span>${holdings.isSample ? '<b>サンプル</b>を表示中' : `読み込み中: <b>${esc(holdings.source)}</b>`}（${holdings.items.length}銘柄）・株価 ${STOCKS.dates[STOCKS.dates.length - 1]} 時点</span>
      <span class="report-actions">
        <button type="button" class="btn" id="reloadHoldings">別のファイルを読み込む</button>
        <button type="button" class="btn" id="clearHoldings">読み込みを解除</button>
      </span>
    </div>
    <div class="subtabs" role="tablist" aria-label="レポートの表示">
      <button type="button" role="tab" data-sub="summary">サマリー</button>
      <button type="button" role="tab" data-sub="cards">銘柄別分析</button>
      <button type="button" role="tab" data-sub="search">銘柄を探す</button>
      <button type="button" role="tab" data-sub="rules">判定ルール</button>
    </div>
    <div class="subpanel" data-sub="summary">${summaryHtml(p)}</div>
    <div class="subpanel" data-sub="cards"></div>
    <div class="subpanel" data-sub="search">${searchHtml()}</div>
    <div class="subpanel" data-sub="rules">${rulesHtml()}</div>`;

  body.querySelectorAll('.subtabs button').forEach(b => b.addEventListener('click', () => { subTab = b.dataset.sub; renderSub(); }));
  body.querySelectorAll('.holdings-table tr[data-code]').forEach(tr => {
    const go = () => {
      subTab = 'cards';
      renderSub();
      document.getElementById(`card-${tr.dataset.code}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    tr.addEventListener('click', go);
    tr.addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
  });
  document.getElementById('reloadHoldings').addEventListener('click', () => { holdings = null; render(); });
  document.getElementById('clearHoldings').addEventListener('click', () => {
    holdings = null;
    try { localStorage.removeItem(STORAGE_KEY); } catch (e) { /* 無視 */ }
    render();
  });
  document.getElementById('stockSearch').addEventListener('change', e => {
    const code = e.target.value.trim().split(/\s+/)[0].toUpperCase();
    const out = document.getElementById('searchResult');
    const s = STOCKS.stocks[code];
    out.innerHTML = s ? stockCard(code, s, null) : `<p class="errors">「${esc(e.target.value)}」は見つかりません。</p>`;
    if (s) drawCardCharts(out);
  });
  renderSub();
}

// テーマ変更時にグラフの色を塗り直す
export function rerender() {
  if (holdings && STOCKS) render();
}

let initialized = false;

export async function show() {
  if (initialized) return;
  initialized = true;
  const loader = document.getElementById('reportLoader');
  const drop = document.getElementById('dropzone');
  document.getElementById('holdingsFile').addEventListener('change', e => e.target.files[0] && readFile(e.target.files[0]));
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => {
    e.preventDefault();
    drop.classList.remove('over');
    if (e.dataTransfer.files[0]) readFile(e.dataTransfer.files[0]);
  });
  document.getElementById('rememberHoldings').addEventListener('change', save);
  document.getElementById('useSample').addEventListener('click', async () => {
    try {
      const items = validate(await loadJson('portfolio/holdings.example.json'));
      holdings = { source: 'holdings.example.json', isSample: true, items };
      render();
    } catch (e) { showLoaderError(e.message); }
  });

  loader.querySelector('h2').textContent = '分析データを読み込み中…';
  try {
    [STOCKS, ANALYSIS] = await Promise.all([loadJson('data/stocks.json'), loadJson('data/analysis.json')]);
  } catch (e) {
    loader.querySelector('h2').textContent = `分析データを読み込めませんでした（${e.message}）`;
    return;
  }
  loader.querySelector('h2').textContent = '保有株 JSON を読み込む';
  restore();
  render();
}
