"""ローカル専用：保有株・市場環境・農業関連先物・YouTuber 最新動画をまとめた HTML レポートを作る。

  python scripts/local_report.py            # data/indicators.json を使ってレポート作成
  python scripts/local_report.py --refresh  # 先に指標データを取り直す
  python scripts/local_report.py --no-open  # ブラウザを開かない

入力: portfolio/holdings.json（なければ holdings.example.json を使用）
出力: reports/report_YYYYMMDD.html と reports/latest.html（どちらも .gitignore 済み）
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
import webbrowser
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analysis as A  # noqa: E402
from fetch_data import remove_glitches  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "indicators.json"
HOLDINGS_PATH = ROOT / "portfolio" / "holdings.json"
EXAMPLE_PATH = ROOT / "portfolio" / "holdings.example.json"
YOUTUBERS_PATH = ROOT / "config" / "youtubers.json"
REPORT_DIR = ROOT / "reports"
YT_RSS = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
ATOM = {"a": "http://www.w3.org/2005/Atom"}


# ---------- 取得 ----------
def load_holdings() -> tuple[list[dict], bool]:
    path = HOLDINGS_PATH if HOLDINGS_PATH.exists() else EXAMPLE_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["holdings"], path == EXAMPLE_PATH


def fetch_prices(tickers: list[str]) -> dict[str, pd.Series]:
    df = yf.download(tickers, period="2y", interval="1d", auto_adjust=False,
                     progress=False, group_by="ticker", threads=True)
    out = {}
    for t in tickers:
        try:
            # group_by="ticker" の列は (ticker, 項目) の2段。1銘柄でも2段になる版がある
            if isinstance(df.columns, pd.MultiIndex):
                s = df[t]["Close"] if t in df.columns.get_level_values(0) else df["Close"][t]
            else:
                s = df["Close"]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[:, 0]
            s = remove_glitches(s.dropna())
            if not s.empty:
                out[t] = s
        except KeyError:
            pass
    return out


def fetch_youtube() -> list[dict]:
    cfg = json.loads(YOUTUBERS_PATH.read_text(encoding="utf-8"))
    rows = []
    for ch in cfg["channels"]:
        try:
            r = requests.get(YT_RSS.format(ch["channel_id"]), timeout=20,
                             headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            e = ET.fromstring(r.content).find("a:entry", ATOM)
            rows.append({"name": ch["name"], "title": e.find("a:title", ATOM).text,
                         "date": e.find("a:published", ATOM).text[:10],
                         "url": e.find("a:link", ATOM).get("href")})
        except Exception as ex:
            rows.append({"name": ch["name"], "error": f"{type(ex).__name__}: {ex}"})
    return rows


# ---------- HTML 部品 ----------
esc = html.escape
LEVEL = {"good": ("▲", "好材料"), "caution": ("▼", "注意"), "info": ("●", "参考")}


def pct(v: float, digits: int = 1) -> str:
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:+.{digits}%}"


def signed_cls(v: float) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)) or v == 0:
        return ""
    return "pos" if v > 0 else "neg"


def findings_html(items: list[A.Finding]) -> str:
    li = []
    for f in items:
        icon, label = LEVEL[f.level]
        ev = f'<span class="ev">{esc(f.evidence)}</span>' if f.evidence else ""
        li.append(f'<li class="{f.level}"><span class="tag">{icon} {label}</span>'
                  f'<span class="ft">{esc(f.text)}</span>{ev}</li>')
    return f'<ul class="findings">{"".join(li)}</ul>'


def score_label(score: int) -> str:
    if score >= 2:
        return "追い風が多い"
    if score <= -2:
        return "逆風が多い"
    return "材料が混在"


def sparkline(vals: list[float]) -> str:
    w, h, pad = 100, 24, 2
    lo, hi = min(vals), max(vals)
    span = hi - lo or 1
    pts = [(pad + i / max(len(vals) - 1, 1) * (w - 2 * pad), pad + (1 - (v - lo) / span) * (h - 2 * pad))
           for i, v in enumerate(vals)]
    d = "".join(f"{'L' if i else 'M'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true">'
            f'<path d="{d}"/><circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="2.2"/></svg>')


def holding_card(r: A.HoldingResult, idx: int) -> str:
    if r.error:
        return f'<article class="card"><h3>{esc(r.name)} <small>{esc(r.ticker)}</small></h3><p class="neg">{esc(r.error)}</p></article>'
    m = r.metrics
    memo = f'<p class="memo">メモ: {esc(r.memo)}</p>' if r.memo else ""
    stats = [
        ("株価", f"{r.price:,.1f} 円", ""), ("損益", f"{m['pnl']:+,.0f} 円（{pct(m['pnl_pct'])}）", signed_cls(m["pnl"])),
        ("1か月", pct(m["ret_1m"]), signed_cls(m["ret_1m"])), ("3か月", pct(m["ret_3m"]), signed_cls(m["ret_3m"])),
        ("1年", pct(m["ret_1y"]), signed_cls(m["ret_1y"])), ("対日経(3か月)", pct(m["rel_3m"]), signed_cls(m["rel_3m"])),
        ("RSI(14)", f"{m['rsi']:.0f}", ""), ("25日線乖離", pct(m["dev25"]), ""),
        ("日経β", f"{m['beta']:.2f}", ""), ("為替感応度", f"{m['fx_beta']:+.2f}（t={m['fx_t']:.1f}）", ""),
        ("年率ボラ", f"{m['vol']:.0%}", ""), ("52週高値比", pct(m["dd_52w"]), ""),
    ]
    stat_html = "".join(f'<div><dt>{k}</dt><dd class="{c}">{v}</dd></div>' for k, v, c in stats)
    return f"""
<article class="card">
  <div class="card-head">
    <h3>{esc(r.name)} <small>{esc(r.ticker)} ・ {r.date}</small></h3>
    <div class="score s{max(-3, min(3, r.score))}"><b>{r.score:+d}</b> {score_label(r.score)}
      <span>{esc('、'.join(r.score_parts))}</span></div>
  </div>
  {memo}
  <div class="card-body">
    <div class="chart"><canvas id="c{idx}" role="img" aria-label="{esc(r.name)} の株価と移動平均（1年）"></canvas></div>
    <dl class="stats">{stat_html}</dl>
  </div>
  {findings_html(r.findings)}
</article>"""


def chart_payload(results: list[A.HoldingResult]) -> str:
    out = []
    for i, r in enumerate(results):
        if r.error or r.history is None:
            continue
        h = r.history
        f = lambda s: [None if pd.isna(v) else round(float(v), 2) for v in s]  # noqa: E731
        out.append({"id": f"c{i}", "labels": [d.strftime("%Y-%m-%d") for d in h.index],
                    "close": f(h["close"]), "ma25": f(h["ma25"]), "ma75": f(h["ma75"]),
                    "cost": r.avg_cost})
    return json.dumps(out, ensure_ascii=False)


# ---------- 組み立て ----------
def build_html(ctx: dict) -> str:
    results: list[A.HoldingResult] = ctx["results"]
    ok = [r for r in results if not r.error]
    total = sum(r.metrics["value"] for r in ok)
    pnl = sum(r.metrics["pnl"] for r in ok)
    cost = total - pnl

    rows = "".join(
        f'<tr><td>{esc(r.name)}<br><small>{esc(r.ticker)}</small></td>'
        f'<td>{r.shares:,.0f}</td><td>{r.price:,.1f}</td><td>{r.metrics["value"]:,.0f}</td>'
        f'<td>{r.metrics.get("weight", 0):.0%}</td>'
        f'<td class="{signed_cls(r.metrics["pnl"])}">{r.metrics["pnl"]:+,.0f}<br><small>{pct(r.metrics["pnl_pct"])}</small></td>'
        f'<td class="{signed_cls(r.metrics["ret_1m"])}">{pct(r.metrics["ret_1m"])}</td>'
        f'<td><span class="chip s{max(-3, min(3, r.score))}">{r.score:+d}</span> {score_label(r.score)}</td></tr>'
        for r in ok)

    com_rows = "".join(
        f'<tr><td>{esc(c["name"])}<br><small>{esc(c["unit"])} ・ {c["date"]}</small></td>'
        f'<td>{c["price"]:,.{c["decimals"]}f}</td><td>{sparkline(c["spark"])}</td>'
        + "".join(f'<td class="{signed_cls(c[k])}">{pct(c[k])}</td>'
                  for k in ("usd_1m", "usd_3m", "usd_1y", "yen_1m", "yen_3m", "yen_1y"))
        + '</tr>' for c in ctx["commodities"])

    yt = "".join(
        f'<li><b>{esc(y["name"])}</b>：<a href="{esc(y["url"])}" target="_blank" rel="noopener">{esc(y["title"])}</a> <small>{y["date"]}</small></li>'
        if "title" in y else f'<li><b>{esc(y["name"])}</b>：<span class="neg">取得失敗（{esc(y["error"])}）</span></li>'
        for y in ctx["youtube"])

    sample = ('<p class="banner">⚠ portfolio/holdings.json が無いため、<b>サンプル</b>（holdings.example.json）で作成しています。'
              'holdings.example.json をコピーして holdings.json を作り、保有株を記入してください。</p>'
              if ctx["is_example"] else "")

    return TEMPLATE.format(
        generated=ctx["generated"], data_updated=ctx["data_updated"], sample=sample,
        total=f"{total:,.0f}", pnl=f"{pnl:+,.0f}", pnl_pct=pct(pnl / cost if cost else float("nan")),
        pnl_cls=signed_cls(pnl), market=findings_html(ctx["market"]),
        portfolio=findings_html(ctx["portfolio"]), rows=rows,
        cards="".join(holding_card(r, i) for i, r in enumerate(results)),
        com_rows=com_rows, com_findings=findings_html(ctx["commodity_findings"]),
        youtube=yt, charts=chart_payload(results),
        rules=RULES_HTML,
    )


RULES_HTML = f"""
<ul>
<li><b>環境スコア</b>＝トレンド（±1）＋日経平均のトレンド（±1）＋為替の追い風・逆風（±1、感応度が有意な銘柄のみ）−過熱（1）。売買の推奨ではなく、材料の向きを数えたもの。</li>
<li><b>トレンド</b>：株価＞25日線＞75日線 かつ 75日線が上向き＝上昇、逆の並びかつ下向き＝下降、それ以外＝もみ合い。</li>
<li><b>過熱・売られすぎ</b>：RSI(14) ≥ {A.RSI_HOT} または 25日線乖離 ≥ {A.DEV25_HOT:+.0%}／RSI ≤ {A.RSI_COLD} または乖離 ≤ {A.DEV25_COLD:+.0%}。</li>
<li><b>日経β・為替感応度</b>：直近1年の日次対数収益率を「日経平均」と「ドル円」で重回帰した係数。|t| ≥ {A.T_SIGNIFICANT:.0f} のときだけ為替の影響を判定に使う。</li>
<li><b>円換算</b>：先物のドル建て価格 × ドル円。輸入コストへの実際の影響に近い。</li>
<li>閾値は <code>scripts/analysis.py</code> の先頭で変更できる。</li>
</ul>"""


TEMPLATE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Portfolio Report</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root {{ color-scheme: light; --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10); --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a;
  --pos:#006300; --neg:#d03b3b; --good-bg:rgba(12,163,12,.08); --bad-bg:rgba(208,59,59,.08); }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ color-scheme: dark; --page:#0d0d0d; --surface:#1a1a19;
  --ink:#fff; --ink2:#c3c2b7; --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --pos:#0ca30c; --neg:#e66767; --good-bg:rgba(12,163,12,.14); --bad-bg:rgba(230,103,103,.14); }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--page); color:var(--ink); line-height:1.55;
  font-family: system-ui,-apple-system,"Segoe UI","Hiragino Sans","Yu Gothic UI",sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:20px 16px 40px; }}
h1 {{ font-size:1.4rem; margin:0; }} h2 {{ font-size:1.1rem; margin:32px 0 10px; }}
h3 {{ font-size:1rem; margin:0; }} small {{ color:var(--muted); font-weight:400; }}
.sub {{ color:var(--ink2); font-size:.85rem; margin:2px 0 0; }}
.banner {{ background:var(--bad-bg); border-radius:8px; padding:10px 14px; font-size:.9rem; }}
.panel, .card {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:16px; }}
.hero {{ display:flex; flex-wrap:wrap; gap:32px; align-items:flex-end; }}
.hero .big {{ font-size:2.4rem; font-weight:600; line-height:1.1; }}
.hero .lbl {{ color:var(--ink2); font-size:.85rem; }}
.pos {{ color:var(--pos); }} .neg {{ color:var(--neg); }}
.findings {{ list-style:none; padding:0; margin:12px 0 0; display:grid; gap:6px; }}
.findings li {{ display:grid; grid-template-columns:5.2em 1fr; column-gap:8px; font-size:.9rem; }}
.findings .tag {{ font-size:.78rem; color:var(--ink2); white-space:nowrap; }}
.findings .good .tag {{ color:var(--pos); }} .findings .caution .tag {{ color:var(--neg); }}
.findings .ev {{ grid-column:2; color:var(--muted); font-size:.8rem; }}
.table-wrap {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; font-size:.88rem; font-variant-numeric:tabular-nums; }}
th, td {{ padding:6px 8px; border-bottom:1px solid var(--grid); text-align:right; white-space:nowrap; }}
th {{ color:var(--ink2); font-weight:600; font-size:.8rem; }}
th:first-child, td:first-child {{ text-align:left; }}
.chip {{ display:inline-block; min-width:2.2em; text-align:center; border-radius:6px; padding:0 6px; font-weight:600; }}
.s1,.s2,.s3 {{ background:var(--good-bg); }} .s-1,.s-2,.s-3 {{ background:var(--bad-bg); }}
.cards {{ display:grid; gap:14px; }}
.card-head {{ display:flex; flex-wrap:wrap; justify-content:space-between; gap:8px; align-items:flex-start; }}
.score {{ border-radius:8px; padding:4px 10px; font-size:.85rem; }}
.score b {{ font-size:1.1rem; }} .score span {{ display:block; color:var(--muted); font-size:.75rem; }}
.memo {{ color:var(--ink2); font-size:.85rem; margin:4px 0 0; }}
.card-body {{ display:grid; grid-template-columns:minmax(0,3fr) minmax(0,2fr); gap:16px; margin-top:10px; }}
.chart {{ position:relative; height:220px; min-width:0; }}
.stats {{ display:grid; grid-template-columns:1fr 1fr; gap:4px 12px; margin:0; font-size:.85rem; }}
.stats dt {{ color:var(--muted); font-size:.75rem; }} .stats dd {{ margin:0 0 4px; font-variant-numeric:tabular-nums; }}
.spark {{ width:100px; height:24px; }} .spark path {{ fill:none; stroke:var(--axis); stroke-width:1.5; }}
.spark circle {{ fill:var(--s1); }}
.yt {{ padding-left:1.2em; margin:0; }} .yt li {{ margin:4px 0; }}
a {{ color:var(--s1); }}
details {{ font-size:.85rem; color:var(--ink2); }} footer {{ color:var(--muted); font-size:.78rem; margin-top:32px; }}
@media (max-width:700px) {{ .card-body {{ grid-template-columns:1fr; }} .hero .big {{ font-size:1.8rem; }} }}
</style></head>
<body><main>
<header><h1>保有株・市場環境レポート</h1>
<p class="sub">作成 {generated} ／ 指標データ更新 {data_updated}</p></header>
{sample}

<h2>サマリー</h2>
<section class="panel">
  <div class="hero">
    <div><div class="lbl">評価額</div><div class="big">{total} 円</div></div>
    <div><div class="lbl">含み損益</div><div class="big {pnl_cls}" style="font-size:1.6rem">{pnl} 円 <small>{pnl_pct}</small></div></div>
  </div>
  <h3 style="margin-top:16px">市場環境（日本株中心）</h3>
  {market}
  <h3 style="margin-top:16px">ポートフォリオ全体</h3>
  {portfolio}
</section>

<h2>保有銘柄一覧</h2>
<section class="panel table-wrap"><table>
<thead><tr><th>銘柄</th><th>株数</th><th>株価</th><th>評価額</th><th>比率</th><th>損益</th><th>1か月</th><th>環境スコア</th></tr></thead>
<tbody>{rows}</tbody></table></section>

<h2>銘柄別の分析</h2>
<div class="cards">{cards}</div>

<h2>農業関連の先物（エネルギー・穀物）</h2>
<section class="panel">
<div class="table-wrap"><table>
<thead><tr><th>品目</th><th>価格</th><th>推移(約半年)</th><th>1か月<br><small>ドル建</small></th><th>3か月<br><small>ドル建</small></th><th>1年<br><small>ドル建</small></th>
<th>1か月<br><small>円換算</small></th><th>3か月<br><small>円換算</small></th><th>1年<br><small>円換算</small></th></tr></thead>
<tbody>{com_rows}</tbody></table></div>
{com_findings}
</section>

<h2>YouTuber 最新動画（1行）</h2>
<section class="panel"><ul class="yt">{youtube}</ul>
<p class="sub">各チャンネルの最新動画タイトルを RSS からそのまま表示しています（要約・加工なし）。内容は各発信者の見解です。</p></section>

<h2>判定ルール</h2>
<details class="panel"><summary>このレポートの判定方法</summary>{rules}</details>

<footer>本レポートは公開データから機械的に計算した状態の整理であり、将来の株価を予測するものでも、売買を推奨するものでもありません。
データ出典: Yahoo Finance（yfinance）, FRED, YouTube RSS。</footer>
</main>
<script>
const CHARTS = {charts};
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
for (const c of CHARTS) {{
  const line = (label, data, color, width, dash) => ({{ label, data, borderColor: color, backgroundColor: color,
    borderWidth: width, borderDash: dash || [], pointRadius: 0, pointHoverRadius: 4, spanGaps: true, tension: 0 }});
  new Chart(document.getElementById(c.id), {{
    type: 'line',
    data: {{ labels: c.labels, datasets: [
      line('株価', c.close, css('--s1'), 2),
      line('25日線', c.ma25, css('--s2'), 1.5),
      line('75日線', c.ma75, css('--s3'), 1.5),
      line('取得単価', c.labels.map(() => c.cost), css('--muted'), 1, [4, 4]),
    ] }},
    options: {{ responsive: true, maintainAspectRatio: false, animation: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{ legend: {{ labels: {{ color: css('--ink2'), boxWidth: 12, boxHeight: 2 }} }},
        tooltip: {{ callbacks: {{ label: x => `${{x.dataset.label}}: ${{x.parsed.y?.toLocaleString('ja-JP')}}` }} }} }},
      scales: {{ x: {{ grid: {{ display: false }}, ticks: {{ color: css('--muted'), maxTicksLimit: 5, maxRotation: 0,
                   callback(v) {{ return this.getLabelForValue(v).slice(0, 7); }} }} }},
                y: {{ grid: {{ color: css('--grid') }}, border: {{ display: false }}, ticks: {{ color: css('--muted') }} }} }} }}
  }});
}}
</script>
</body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="先に scripts/fetch_data.py を実行する")
    ap.add_argument("--no-open", action="store_true", help="ブラウザを開かない")
    args = ap.parse_args()

    if args.refresh or not DATA_PATH.exists():
        import fetch_data
        fetch_data.main()

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    series = data["series"]
    holdings, is_example = load_holdings()

    market, mctx = A.market_environment(series)
    n225 = A.to_series(series["n225"]["history"])
    usdjpy = A.to_series(series["usdjpy"]["history"])

    tickers = [h.get("ticker") or f"{h['code']}.T" for h in holdings]
    print(f"保有 {len(tickers)} 銘柄の株価を取得中…")
    prices = fetch_prices(tickers)

    results = []
    for h, t in zip(holdings, tickers):
        r = A.HoldingResult(code=h.get("code", ""), name=h["name"], ticker=t, shares=h["shares"],
                            avg_cost=h["avg_cost"], memo=h.get("memo", ""))
        if t not in prices or len(prices[t]) < 100:
            r.error = "株価を取得できませんでした（証券コード・ticker を確認してください）"
        else:
            try:
                A.analyze_holding(r, prices[t], n225, usdjpy, mctx)
            except Exception as ex:
                r.error = f"分析エラー: {type(ex).__name__}: {ex}"
        results.append(r)
    portfolio = A.portfolio_findings(results)

    com = A.commodities(series)
    print("YouTube RSS を取得中…")
    youtube = fetch_youtube()

    now = datetime.now()
    updated = datetime.fromisoformat(data["updated_at"]).astimezone().strftime("%Y-%m-%d %H:%M")
    page = build_html({
        "generated": now.strftime("%Y-%m-%d %H:%M"), "data_updated": updated,
        "is_example": is_example, "results": results, "market": market,
        "portfolio": portfolio, "commodities": com,
        "commodity_findings": A.commodity_findings(com, now.month), "youtube": youtube,
    })

    REPORT_DIR.mkdir(exist_ok=True)
    dated = REPORT_DIR / f"report_{now:%Y%m%d}.html"
    for p in (dated, REPORT_DIR / "latest.html"):
        p.write_text(page, encoding="utf-8")
    print(f"レポートを作成しました: {dated}")
    if not args.no_open:
        webbrowser.open(dated.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
