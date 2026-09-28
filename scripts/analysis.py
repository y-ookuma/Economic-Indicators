"""保有株・市場環境・先物の数値分析と、ルールベースの判定。

AI は使わず、すべての判定に根拠となる数値を添える。
判定は「現在の状態の整理」であり、将来の価格を予測するものではない。
閾値は下の定数で調整できる。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# ---- 閾値（必要に応じて調整） ----
RSI_HOT, RSI_COLD = 70, 30
DEV25_HOT, DEV25_COLD = 0.10, -0.10     # 25日線からの乖離率
DRAWDOWN_ALERT = -0.20                  # 52週高値からの下落率
BETA_HIGH = 1.2
WEIGHT_ALERT = 0.30                     # 1銘柄の比率
LOSS_ALERT = -0.20                      # 含み損率
T_SIGNIFICANT = 2.0                     # 感応度の |t値| がこれ以上なら有意とみなす
VIX_CALM, VIX_STRESS = 15, 25
LOOKBACK_1Y = 245                       # 1年 ≒ 245 営業日（東証）


@dataclass
class Finding:
    level: str          # "good" / "caution" / "info"
    text: str
    evidence: str = ""


@dataclass
class HoldingResult:
    code: str
    name: str
    ticker: str
    shares: float
    avg_cost: float
    memo: str
    price: float = float("nan")
    date: str = ""
    metrics: dict = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    score: int = 0
    score_parts: list[str] = field(default_factory=list)
    history: pd.DataFrame | None = None   # close, ma25, ma75
    error: str = ""


# ---------- 基本計算 ----------
def to_series(history: list[list]) -> pd.Series:
    s = pd.Series({pd.Timestamp(d): v for d, v in history}, dtype=float)
    return s.sort_index()


def ret(s: pd.Series, n: int) -> float:
    if len(s) <= n:
        return float("nan")
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1)


def ret_days(s: pd.Series, days: int) -> float:
    """暦日ベースの変化率（月次・日次どちらの系列にも使える）"""
    past = s[s.index <= s.index[-1] - pd.Timedelta(days=days)]
    if past.empty:
        return float("nan")
    return float(s.iloc[-1] / past.iloc[-1] - 1)


def rsi(s: pd.Series, n: int = 14) -> float:
    delta = s.diff().dropna()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up.iloc[-1] / down.iloc[-1] if down.iloc[-1] else np.inf
    return float(100 - 100 / (1 + rs))


def trend(s: pd.Series) -> tuple[str, str]:
    """移動平均の並びと 75日線の傾きでトレンドを分類する"""
    ma25, ma75 = s.rolling(25).mean(), s.rolling(75).mean()
    p, a, b = s.iloc[-1], ma25.iloc[-1], ma75.iloc[-1]
    slope = ma75.iloc[-1] / ma75.iloc[-21] - 1 if len(ma75.dropna()) > 21 else 0
    ev = f"株価 {p:,.0f} / 25日線 {a:,.0f} / 75日線 {b:,.0f}、75日線の20日変化 {slope:+.1%}"
    if p > a > b and slope > 0:
        return "up", ev
    if p < a < b and slope < 0:
        return "down", ev
    return "flat", ev


def regress(y: pd.Series, xs: dict[str, pd.Series]) -> dict[str, tuple[float, float]]:
    """OLS。{説明変数名: (係数, t値)} を返す"""
    df = pd.concat([y.rename("y"), *[x.rename(k) for k, x in xs.items()]], axis=1).dropna()
    if len(df) < 60:
        return {}
    X = np.column_stack([np.ones(len(df)), df[list(xs)].values])
    Y = df["y"].values
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    resid = Y - X @ beta
    sigma2 = resid @ resid / (len(df) - X.shape[1])
    se = np.sqrt(np.diag(sigma2 * np.linalg.inv(X.T @ X)))
    return {k: (float(beta[i + 1]), float(beta[i + 1] / se[i + 1])) for i, k in enumerate(xs)}


def log_returns(s: pd.Series) -> pd.Series:
    s = s.copy()
    s.index = s.index.normalize().tz_localize(None) if s.index.tz is not None else s.index.normalize()
    return np.log(s).diff().dropna()


# ---------- 市場環境 ----------
TREND_JA = {"up": "上昇トレンド", "down": "下降トレンド", "flat": "もみ合い・転換局面"}


def market_environment(series: dict) -> tuple[list[Finding], dict]:
    out: list[Finding] = []
    ctx: dict = {}

    n225 = to_series(series["n225"]["history"])
    t, ev = trend(n225)
    ctx["n225_trend"] = t
    out.append(Finding("good" if t == "up" else "caution" if t == "down" else "info",
                       f"日経平均は{TREND_JA[t]}", ev))

    vix = series["vix"]["latest"]["value"]
    lvl = "安定" if vix < VIX_CALM else "警戒" if vix > VIX_STRESS else "通常"
    out.append(Finding("caution" if vix > VIX_STRESS else "info",
                       f"VIX は {vix:.1f}（{lvl}水準）",
                       f"{VIX_CALM}未満=安定、{VIX_STRESS}超=リスクオフ警戒。リスクオフ時は円高・日本株安が起きやすい"))

    fx = to_series(series["usdjpy"]["history"])
    fx1m = ret_days(fx, 30)
    ctx["usdjpy_1m"] = fx1m
    out.append(Finding("info", f"ドル円は1か月で {fx1m:+.1%}（{'円安' if fx1m > 0 else '円高'}方向）",
                       f"現在 {fx.iloc[-1]:.2f} 円"))

    jp10 = to_series(series["jp10y"]["history"])
    d = jp10.iloc[-1] - jp10[jp10.index <= jp10.index[-1] - pd.Timedelta(days=180)].iloc[-1]
    ctx["jp10y_6m"] = d
    out.append(Finding("info", f"日本10年金利は半年で {d:+.2f}pt（{jp10.iloc[-1]:.2f}%）",
                       "金利上昇は銀行・保険に追い風、不動産・高PER成長株に逆風となりやすい"))

    spread = series["us_t10y2y"]["latest"]["value"]
    if spread < 0:
        out.append(Finding("caution", f"米国は逆イールド（10年-2年 {spread:+.2f}pt）",
                           "過去の米景気後退の前に多く観測された"))

    return out, ctx


# ---------- 先物（円換算付き） ----------
COMMODITY_KEYS = ["wti", "brent", "heating_oil", "natgas", "corn", "soybean", "wheat", "soymeal", "rice"]


def commodities(series: dict) -> list[dict]:
    fx = to_series(series["usdjpy"]["history"])
    rows = []
    for k in COMMODITY_KEYS:
        if k not in series:
            continue
        s = to_series(series[k]["history"])
        yen = (s * fx.reindex(s.index, method="ffill")).dropna()
        row = {"key": k, "name": series[k]["name"], "unit": series[k]["unit"],
               "note": series[k].get("note", ""), "price": s.iloc[-1],
               "date": s.index[-1].strftime("%Y-%m-%d"), "decimals": series[k]["decimals"],
               "spark": s.iloc[-120:].tolist()}
        for label, days in (("1m", 30), ("3m", 91), ("1y", 365)):
            row[f"usd_{label}"] = ret_days(s, days)
            row[f"yen_{label}"] = ret_days(yen, days)
        rows.append(row)
    return rows


def commodity_findings(rows: list[dict], month: int) -> list[Finding]:
    by = {r["key"]: r for r in rows}
    out = []
    ho = by.get("heating_oil")
    if ho:
        lvl = "caution" if ho["yen_3m"] > 0.10 else "good" if ho["yen_3m"] < -0.10 else "info"
        season = "暖房シーズン前のため、A重油の手当て時期を検討する材料になる。" if month in (9, 10, 11) else ""
        out.append(Finding(lvl, f"暖房油（A重油の参考）は円換算で3か月 {ho['yen_3m']:+.1%}",
                           f"ドル建て {ho['usd_3m']:+.1%}。{season}"))
    ng = by.get("natgas")
    if ng:
        lvl = "caution" if ng["yen_3m"] > 0.15 else "info"
        out.append(Finding(lvl, f"天然ガス（窒素肥料の原料）は円換算で3か月 {ng['yen_3m']:+.1%}",
                           "尿素などの輸入肥料価格には数か月遅れて波及しやすい"))
    grains = [by[k] for k in ("corn", "soybean", "wheat", "soymeal") if k in by]
    if grains:
        avg = np.mean([g["yen_3m"] for g in grains])
        out.append(Finding("caution" if avg > 0.10 else "info",
                           f"穀物4品目の円換算3か月変化は平均 {avg:+.1%}",
                           "、".join(f"{g['name']} {g['yen_3m']:+.1%}" for g in grains)))
    return out


# ---------- 保有株 ----------
def analyze_holding(h: HoldingResult, close: pd.Series, n225: pd.Series, usdjpy: pd.Series,
                    ctx: dict) -> None:
    close = close.dropna()
    close.index = close.index.tz_localize(None) if close.index.tz is not None else close.index
    p = float(close.iloc[-1])
    h.price, h.date = p, close.index[-1].strftime("%Y-%m-%d")

    ma25, ma75 = close.rolling(25).mean(), close.rolling(75).mean()
    h.history = pd.DataFrame({"close": close, "ma25": ma25, "ma75": ma75}).iloc[-LOOKBACK_1Y:]

    m = h.metrics
    m["value"] = p * h.shares
    m["pnl"] = (p - h.avg_cost) * h.shares
    m["pnl_pct"] = p / h.avg_cost - 1 if h.avg_cost else float("nan")
    m["ret_1m"], m["ret_3m"], m["ret_1y"] = ret(close, 21), ret(close, 63), ret(close, LOOKBACK_1Y)
    m["rsi"] = rsi(close)
    m["dev25"] = p / ma25.iloc[-1] - 1
    m["dd_52w"] = p / close.iloc[-LOOKBACK_1Y:].max() - 1
    lr = log_returns(close).iloc[-LOOKBACK_1Y:]
    m["vol"] = float(lr.std() * np.sqrt(245))

    # 日経平均・ドル円への感応度（1年、日次対数収益率の重回帰）
    # 日本株は前日の米国市場の影響を受けるため、ドル円は東京時間の終値とほぼ同時点の値を使う
    reg = regress(lr, {"n225": log_returns(n225), "usdjpy": log_returns(usdjpy)})
    m["beta"], m["beta_t"] = reg.get("n225", (float("nan"), 0))
    m["fx_beta"], m["fx_t"] = reg.get("usdjpy", (float("nan"), 0))
    m["rel_3m"] = m["ret_3m"] - ret(n225, 63)

    f, parts = h.findings, h.score_parts
    score = 0

    t, ev = trend(close)
    f.append(Finding("good" if t == "up" else "caution" if t == "down" else "info", TREND_JA[t], ev))
    score += {"up": 1, "down": -1, "flat": 0}[t]
    parts.append(f"トレンド {({'up': '+1', 'down': '-1', 'flat': '±0'})[t]}")

    mk = ctx["n225_trend"]
    score += {"up": 1, "down": -1, "flat": 0}[mk]
    parts.append(f"市場(日経) {({'up': '+1', 'down': '-1', 'flat': '±0'})[mk]}")

    # 25日線と75日線のクロス（直近10営業日）
    diff = (ma25 - ma75).dropna().iloc[-11:]
    if len(diff) == 11 and diff.iloc[0] < 0 < diff.iloc[-1]:
        f.append(Finding("good", "直近10日以内にゴールデンクロス（25日線が75日線を上抜け）"))
    elif len(diff) == 11 and diff.iloc[0] > 0 > diff.iloc[-1]:
        f.append(Finding("caution", "直近10日以内にデッドクロス（25日線が75日線を下抜け）"))

    if m["rsi"] >= RSI_HOT or m["dev25"] >= DEV25_HOT:
        f.append(Finding("caution", "短期的に過熱気味（追加購入は押し目を待つ判断材料）",
                         f"RSI {m['rsi']:.0f}、25日線乖離 {m['dev25']:+.1%}"))
        score -= 1
        parts.append("過熱 -1")
    elif m["rsi"] <= RSI_COLD or m["dev25"] <= DEV25_COLD:
        f.append(Finding("info", "短期的に売られすぎの水準（下降トレンド中は反発が続かないこともある）",
                         f"RSI {m['rsi']:.0f}、25日線乖離 {m['dev25']:+.1%}"))

    if m["dd_52w"] <= DRAWDOWN_ALERT:
        f.append(Finding("caution", f"52週高値から {m['dd_52w']:.0%} 下落"))

    if not np.isnan(m["beta"]) and m["beta"] >= BETA_HIGH:
        f.append(Finding("info", "日経平均より値動きが大きい銘柄",
                         f"β={m['beta']:.2f}（日経 1% の変動に対して平均 {m['beta']:.2f}%）"))

    if abs(m["fx_t"]) >= T_SIGNIFICANT:
        kind = "円安メリット型" if m["fx_beta"] > 0 else "円高メリット型"
        fx1m = ctx["usdjpy_1m"]
        tail = (m["fx_beta"] > 0) == (fx1m > 0)
        f.append(Finding("good" if tail else "caution",
                         f"{kind}：直近1か月の為替（{fx1m:+.1%}）は{'追い風' if tail else '逆風'}",
                         f"日経平均の影響を除いたドル円感応度 {m['fx_beta']:+.2f}（t={m['fx_t']:.1f}）"))
        score += 1 if tail else -1
        parts.append(f"為替 {'+1' if tail else '-1'}")

    if m["pnl_pct"] <= LOSS_ALERT:
        f.append(Finding("caution", f"含み損 {m['pnl_pct']:.0%}：購入時の理由が今も成り立つか再確認を"))

    h.score = score


def portfolio_findings(results: list[HoldingResult]) -> list[Finding]:
    ok = [r for r in results if not r.error]
    total = sum(r.metrics["value"] for r in ok)
    out = []
    if not total:
        return out
    for r in ok:
        r.metrics["weight"] = r.metrics["value"] / total
        if r.metrics["weight"] >= WEIGHT_ALERT:
            out.append(Finding("caution", f"{r.name} が評価額の {r.metrics['weight']:.0%} を占める（集中）",
                               f"{WEIGHT_ALERT:.0%} 以上で表示"))
    betas = [(r.metrics["beta"], r.metrics["weight"]) for r in ok if not np.isnan(r.metrics["beta"])]
    if betas:
        pb = sum(b * w for b, w in betas) / sum(w for _, w in betas)
        out.append(Finding("info", f"ポートフォリオ全体の日経平均β ≒ {pb:.2f}",
                           f"日経平均が 10% 下落すると、評価額は単純計算で約 {pb * 10:.0f}%（{total * pb * 0.10:,.0f} 円）減る"))
    fx = [(r.metrics["fx_beta"], r.metrics["weight"]) for r in ok
          if abs(r.metrics["fx_t"]) >= T_SIGNIFICANT]
    if fx:
        pf = sum(b * w for b, w in fx)
        out.append(Finding("info", f"為替感応度が有意な銘柄の合計寄与 {pf:+.2f}",
                           f"ドル円が 5% 円高になると、評価額は約 {-pf * 5:+.1f}% 変わる（日経平均一定の場合）"))
    return out
