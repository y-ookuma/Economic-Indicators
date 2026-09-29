"""data/indicators.json を元に、Web アプリ用の分析データを作る。

  python scripts/build_analysis.py

出力:
  data/analysis.json       … 市場環境・先物の判定・YouTuber 最新動画・閾値
  data/stocks.json         … 東証プライム全銘柄＋ETF・ETN＋ウォッチリストの指標・判定（株価の履歴は含めない）
  data/prices/{code}.json  … 銘柄ごとの終値（約1年＋75日分）。ブラウザは表示する銘柄の分だけ取得する

保有情報は扱わない。保有 JSON はブラウザで読み込み、端末内でこのデータと突き合わせる。
分析対象を広く取ることで、公開データからどの銘柄を保有しているかが分からないようにしている。
"""

from __future__ import annotations

import io
import json
import math
import re
import shutil
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analysis as A  # noqa: E402
from fetch_data import remove_glitches  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PRICES = DATA / "prices"
JPX_LIST = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xlsx"
JPX_SEGMENTS = {"プライム（内国株式）", "ETF・ETN"}
N225_CSV = "https://indexes.nikkei.co.jp/nkave/archives/file/nikkei_stock_average_weight_jp.csv"
YT_RSS = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
ATOM = {"a": "http://www.w3.org/2005/Atom"}
CHART_DAYS = 245 + 75          # 1年分＋75日線の計算に必要な分
CHUNK = 100                    # yfinance に一度に問い合わせる銘柄数
UA = {"User-Agent": "Mozilla/5.0 (Economic-Indicators)"}
CODE_RE = re.compile(r"\d{3}[0-9A-Z]")   # 285A のような英字入りコードもある


def clean(o):
    """NaN/inf を null にし、浮動小数を丸めて JSON を小さくする"""
    if isinstance(o, float):
        return None if math.isnan(o) or math.isinf(o) else round(o, 4)
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    return o


def write_json(path: Path, obj, quiet: bool = False) -> None:
    path.write_text(json.dumps(clean(obj), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if not quiet:
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size / 1024:,.0f} KB)")


# ---------- 銘柄ユニバース ----------
def load_jpx() -> tuple[list[dict], str]:
    """JPX「東証上場銘柄一覧」からプライム（内国株式）と ETF・ETN を取得する"""
    r = requests.get(JPX_LIST, headers=UA, timeout=60)
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content), dtype=str)
    df = df[df["市場・商品区分"].isin(JPX_SEGMENTS)]
    stocks = []
    for _, row in df.iterrows():
        code = str(row["コード"]).strip()
        if not CODE_RE.fullmatch(code):
            continue
        etf = row["市場・商品区分"] == "ETF・ETN"
        # 全角英数字を半角にそろえる（ＬＩＸＩＬ → LIXIL）。検索しやすくするため
        name = unicodedata.normalize("NFKC", str(row["銘柄名"])).strip()
        stocks.append({"code": code, "name": name,
                       "sector": "ETF・ETN" if etf else str(row["33業種区分"]).strip(),
                       "market": "ETF" if etf else "プライム"})
    return stocks, f"東証プライム＋ETF・ETN（JPX {df['日付'].iloc[0]} 時点）"


def load_n225_codes() -> set[str] | None:
    """日経225採用銘柄のコード（日経公式 CSV。著作物のためコード以外は使わない）"""
    try:
        r = requests.get(N225_CSV, headers=UA, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.content.decode("cp932")), dtype=str)
        return {c.strip() for c in df["コード"].dropna() if CODE_RE.fullmatch(c.strip())}
    except Exception as e:
        print(f"WARN 日経225 の構成銘柄を取得できません: {e}", file=sys.stderr)
        return None


def load_universe() -> tuple[list[dict], str]:
    prev = json.loads((DATA / "stocks.json").read_text(encoding="utf-8")) if (DATA / "stocks.json").exists() else None
    try:
        stocks, source = load_jpx()
    except Exception as e:
        print(f"WARN JPX の銘柄一覧を取得できません: {e}", file=sys.stderr)
        if not prev:
            raise
        stocks = [{"code": c, **{k: s.get(k) for k in ("name", "sector", "market")}}
                  for c, s in prev["stocks"].items() if s.get("market") in ("プライム", "ETF")]
        source = prev.get("universe_source", "") + "（前回の銘柄一覧）"

    n225 = load_n225_codes()
    if n225 is None and prev:
        n225 = {c for c, s in prev["stocks"].items() if s.get("n225")}
    for s in stocks:
        s["n225"] = s["code"] in (n225 or set())

    # ウォッチリスト（プライム・ETF 以外の銘柄や米国株など）
    wl = json.loads((ROOT / "config" / "watchlist.json").read_text(encoding="utf-8"))["stocks"]
    have = {s["code"] for s in stocks}
    for w in wl:
        if w["code"] not in have:
            stocks.append({"code": w["code"], "name": w["name"], "ticker": w.get("ticker"),
                           "sector": w.get("sector", "その他"), "market": "その他", "n225": False})
    for s in stocks:
        s["ticker"] = s.get("ticker") or f"{s['code']}.T"
    return stocks, source


# ---------- 株価 ----------
def _download(tickers: list[str]) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    df = yf.download(tickers, period="2y", interval="1d", auto_adjust=False,
                     progress=False, group_by="ticker", threads=True)
    for t in tickers:
        try:
            s = df[t]["Close"] if isinstance(df.columns, pd.MultiIndex) else df["Close"]
        except KeyError:
            continue
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        s = s.dropna()
        if s.empty:
            continue
        if isinstance(s.index, pd.DatetimeIndex) and s.index.tz is not None:
            s.index = s.index.tz_localize(None)
        out[t] = s
    return out


def fetch_closes(tickers: list[str]) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for i in range(0, len(tickers), CHUNK):
        out |= _download(tickers[i:i + CHUNK])
        print(f"  prices {min(i + CHUNK, len(tickers))}/{len(tickers)}")
        time.sleep(1)                       # Yahoo の流量制限を避ける
    missing = [t for t in tickers if t not in out]
    if missing:                             # 一時的な失敗に備えて1回だけ取り直す
        print(f"  retry {len(missing)} tickers")
        time.sleep(10)
        for i in range(0, len(missing), CHUNK):
            out |= _download(missing[i:i + CHUNK])
    # 異常値の除去と、分析に足りない銘柄（上場直後・売買の少ない ETN など）の除外
    cleaned = {}
    for t, s in out.items():
        s = remove_glitches(s)
        if len(s) >= 100:
            cleaned[t] = s
    return cleaned


# ---------- YouTube ----------
def fetch_youtube() -> list[dict]:
    cfg = json.loads((ROOT / "config" / "youtubers.json").read_text(encoding="utf-8"))
    rows = []
    for ch in cfg["channels"]:
        try:
            r = requests.get(YT_RSS.format(ch["channel_id"]), timeout=20, headers=UA)
            r.raise_for_status()
            entries = ET.fromstring(r.content).findall("a:entry", ATOM)
            rows.append({"name": ch["name"], "channel_id": ch["channel_id"], "videos": [
                {"title": e.find("a:title", ATOM).text, "date": e.find("a:published", ATOM).text[:10],
                 "url": e.find("a:link", ATOM).get("href")} for e in entries[:5]]})
        except Exception as ex:
            rows.append({"name": ch["name"], "channel_id": ch["channel_id"],
                         "error": f"{type(ex).__name__}: {ex}"})
    return rows


def main() -> int:
    ind = json.loads((DATA / "indicators.json").read_text(encoding="utf-8"))
    series = ind["series"]
    now = datetime.now(timezone.utc)

    market, ctx = A.market_environment(series)
    com = A.commodities(series)
    youtube = fetch_youtube()
    write_json(DATA / "analysis.json", {
        "updated_at": now.isoformat(timespec="seconds"),
        "thresholds": A.THRESHOLDS,
        "context": ctx,
        "market": A.findings_json(market),
        "commodities": com,
        "commodity_findings": A.findings_json(A.commodity_findings(com, now.astimezone().month)),
        "youtube": youtube,
    })

    universe, source = load_universe()
    print(f"universe: {len(universe)} 銘柄 / {source}")
    t0 = time.time()
    closes = fetch_closes([s["ticker"] for s in universe])
    print(f"prices: {len(closes)}/{len(universe)} 銘柄 ({time.time() - t0:.0f}s)")
    n225 = A.to_series(series["n225"]["history"])
    usdjpy = A.to_series(series["usdjpy"]["history"])

    # 東証の営業日（日経平均の日付）を共通の日付軸にする
    cal_index = pd.DatetimeIndex(sorted(set().union(*[set(s.index[-CHART_DAYS:]) for s in closes.values()
                                                      if s.index[-1] >= n225.index[-1] - pd.Timedelta(days=10)]))
                                 )[-CHART_DAYS:]

    if PRICES.exists():
        shutil.rmtree(PRICES)
    PRICES.mkdir(parents=True)
    stocks: dict[str, dict] = {}
    skipped = []
    for s in universe:
        close = closes.get(s["ticker"])
        if close is None:
            skipped.append(s["code"])
            continue
        try:
            res = A.analyze_stock(close, n225, usdjpy, ctx)
        except Exception as ex:
            print(f"FAIL {s['code']} {type(ex).__name__}: {ex}", file=sys.stderr)
            skipped.append(s["code"])
            continue
        stocks[s["code"]] = {k: s[k] for k in ("name", "sector", "market", "ticker", "n225")} | res
        aligned = close.reindex(cal_index)
        write_json(PRICES / f"{s['code']}.json",
                   [None if pd.isna(v) else round(float(v), 1) for v in aligned], quiet=True)

    write_json(DATA / "stocks.json", {
        "updated_at": now.isoformat(timespec="seconds"),
        "universe_source": source,
        "dates": [d.strftime("%Y-%m-%d") for d in cal_index],
        "stocks": stocks,
        "skipped": skipped,
    })
    print(f"stocks ok={len(stocks)} skipped={len(skipped)}（株価なし・上場1年未満の銘柄など）")
    return 0 if stocks else 1


if __name__ == "__main__":
    sys.exit(main())
