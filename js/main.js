// エントリーポイント：タブ切り替え・テーマ・データ読み込み
// URL のハッシュでタブを覚える（#market/n225, #report, #futures, #youtube）
import { loadJson } from './util.js';
import * as market from './market.js';
import * as report from './report.js';
import * as futures from './futures.js';
import * as youtube from './youtube.js';

const TABS = ['market', 'report', 'futures', 'youtube'];
let IND = null;
let analysisPromise = null;
const getAnalysis = () => (analysisPromise ??= loadJson('data/analysis.json'));

function parseHash() {
  const [tab, key] = location.hash.slice(1).split('/');
  if (TABS.includes(tab)) return { tab, key };
  if (tab && IND?.series[tab]) return { tab: 'market', key: tab };  // 旧形式 #n225
  return { tab: 'market', key: null };
}

async function showTab(tab, key) {
  document.querySelectorAll('.tabs [role="tab"]').forEach(b => {
    const on = b.dataset.tab === tab;
    b.setAttribute('aria-selected', on);
    b.tabIndex = on ? 0 : -1;
  });
  document.querySelectorAll('.tab-panel').forEach(p => { p.hidden = p.id !== `panel-${tab}`; });
  if (!location.hash.startsWith(`#${tab}`)) history.replaceState(null, '', `#${tab}${key ? '/' + key : ''}`);

  try {
    if (tab === 'market') market.render();
    if (tab === 'report') await report.show();
    if (tab === 'futures') futures.show(IND, await getAnalysis());
    if (tab === 'youtube') youtube.show(await getAnalysis());
  } catch (e) {
    document.getElementById(`panel-${tab}`).insertAdjacentHTML('afterbegin',
      `<p class="errors">データを読み込めませんでした（${e.message}）</p>`);
  }
}

function initTabs() {
  const buttons = [...document.querySelectorAll('.tabs [role="tab"]')];
  buttons.forEach((b, i) => {
    b.addEventListener('click', () => showTab(b.dataset.tab));
    b.addEventListener('keydown', e => {  // 左右キーでタブ移動
      const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (!d) return;
      const next = buttons[(i + d + buttons.length) % buttons.length];
      next.focus();
      showTab(next.dataset.tab);
    });
  });
}

// ---------- テーマ ----------
function rerenderCharts() {
  const { tab } = parseHash();
  if (tab === 'market') market.render();
  if (tab === 'report') report.rerender();
  if (tab === 'futures') futures.rerender();
}

function applyTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem('theme'); } catch (e) { /* 保存不可の環境 */ }
  applyTheme(saved);
  document.getElementById('themeToggle').addEventListener('click', () => {
    const root = document.documentElement;
    const dark = root.dataset.theme === 'dark' || (!root.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
    const next = dark ? 'light' : 'dark';
    try { localStorage.setItem('theme', next); } catch (e) { /* 無視 */ }
    applyTheme(next);
    rerenderCharts();
  });
}

async function main() {
  initTheme();
  initTabs();
  try {
    IND = await loadJson('data/indicators.json');
  } catch (e) {
    document.getElementById('updated').textContent = `データを読み込めませんでした（${e.message}）`;
    return;
  }
  const t = new Date(IND.updated_at);
  document.getElementById('updated').textContent =
    `最終更新: ${t.toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })} JST`;

  const { tab, key } = parseHash();
  market.init(IND, key);
  showTab(tab, key);
}

main();
