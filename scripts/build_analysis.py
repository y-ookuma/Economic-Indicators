"""data/indicators.json を元に、Web アプリ用の分析データを作る。

  python scripts/build_analysis.py

出力:
  data/analysis.json … 市場環境・先物の判定・YouTuber 最新動画・閾値
  data/stocks.json   … 日経225採用銘柄＋ウォッチリストの各銘柄の指標・判定・終値（約1年分）

保有情報は扱わない。保有 JSON はブラウザで読み込み、端末内でこのデータと突き合わせる。
"""

from __future__ import annotations

import io
import json
import math
import re
import sys
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
N225_CSV = "https://indexes.nikkei.co.jp/nkave/archives/file/nikkei_stock_average_weight_jp.csv"
YT_RSS = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
ATOM = {"a": "http://www.w3.org/2005/Atom"}
CHART_DAYS = 245 + 75          # 1年分＋75日線の計算に必要な分
CHUNK = 60                     # yfinance に一度に問い合わせる銘柄数
UA = {"User-Agent": "Mozilla/5.0 (Economic-Indicators)"}


def clean(o):
    """NaN/inf を null にし、浮動小数を丸めて JSON を小さくする"""
    if isinstance(o, float):
        return None if math.isnan(o) or math.isinf(o) else round(o, 4)
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    return o


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(clean(obj), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size / 1024:,.0f} KB)")


# ---------- 銘柄ユニバース ----------
def load_universe() -> tuple[list[dict], str]:
    """日経225（日経公式 CSV から銘柄コード・社名・業種のみ使用）＋ config/watchlist.json

    CSV は日経の著作物のため、ウエートなどの数値は公開データに含めない。
    """
    stocks: list[dict] = []
    source = ""
    try:
        r = requests.get(N225_CSV, headers=UA, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.content.decode("cp932")), dtype=str)
        for _, row in df.iterrows():
            code = str(row["コード"]).strip()
            if not re.fullmatch(r"\d{3}[0-9A-Z]", code):  # 末尾は注意書きの行。285A のような英字入りコードもある
                continue
            stocks.append({"code": code, "name": row["社名"].strip(),
                           "sector": row["業種"].strip(), "n225": True})
        source = f"日経225（{df['日付'].iloc[0]} 時点）"
    except Exception as e:
        print(f"WARN 日経225 の構成銘柄を取得できません: {e}", file=sys.stderr)
        prev = DATA / "stocks.json"
        if prev.exists():  # 前回の構成銘柄を使う
            old = json.loads(prev.read_text(encoding="utf-8"))
            stocks = [{k: v for k, v in s.items() if k in ("code", "name", "sector", "n225")}
                      | {"code": c} for c, s in old["stocks"].items() if s.get("n225")]
            source = old.get("universe_source", "") + "（前回の構成銘柄）"

    wl = json.loads((ROOT / "config" / "watchlist.json").read_text(encoding="utf-8"))["stocks"]
    have = {s["code"] for s in stocks}
    for w in wl:
        if w["code"] not in have:
            stocks.append({"code": w["code"], "name": w["name"], "ticker": w.get("ticker"),
                           "sector": w.get("sector", "ウォッチリスト"), "n225": False})
    for s in stocks:
        s["ticker"] = s.get("ticker") or f"{s['code']}.T"
    return stocks, source


def fetch_closes(tickers: list[str]) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for i in range(0, len(tickers), CHUNK):
        chunk = tickers[i:i + CHUNK]
        df = yf.download(chunk, period="2y", interval="1d", auto_adjust=False,
                         progress=False, group_by="ticker", threads=True)
        for t in chunk:
            try:
                s = df[t]["Close"] if isinstance(df.columns, pd.MultiIndex) else df["Close"]
                if isinstance(s, pd.DataFrame):
                    s = s.iloc[:, 0]
                s = s.dropna()
                if isinstance(s.index, pd.DatetimeIndex) and s.index.tz is not None:
                    s.index = s.index.tz_localize(None)
                s = remove_glitches(s)
                if len(s) >= 100:
                    out[t] = s
            except KeyError:
                pass
        print(f"  prices {min(i + CHUNK, len(tickers))}/{len(tickers)}")
    return out


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
    closes = fetch_closes([s["ticker"] for s in universe])
    n225 = A.to_series(series["n225"]["history"])
    usdjpy = A.to_series(series["usdjpy"]["history"])

    # 全銘柄で共通の日付軸（東証の営業日）に揃えて終値を格納する
    calendar = sorted(set().union(*[set(s.index[-CHART_DAYS:]) for s in closes.values()]))[-CHART_DAYS:]
    cal_index = pd.DatetimeIndex(calendar)

    stocks: dict[str, dict] = {}
    failed = []
    for s in universe:
        close = closes.get(s["ticker"])
        if close is None:
            failed.append(s["code"])
            continue
        try:
            res = A.analyze_stock(close, n225, usdjpy, ctx)
        except Exception as ex:
            print(f"FAIL {s['code']} {type(ex).__name__}: {ex}", file=sys.stderr)
            failed.append(s["code"])
            continue
        aligned = close.reindex(cal_index)
        stocks[s["code"]] = {**{k: s[k] for k in ("name", "sector", "ticker", "n225") if k in s},
                             **res,
                             "close": [None if pd.isna(v) else round(float(v), 1) for v in aligned]}

    write_json(DATA / "stocks.json", {
        "updated_at": now.isoformat(timespec="seconds"),
        "universe_source": source,
        "dates": [d.strftime("%Y-%m-%d") for d in cal_index],
        "stocks": stocks,
        "failed": failed,
    })
    print(f"stocks ok={len(stocks)} failed={len(failed)} {failed[:10]}")
    return 0 if stocks else 1


if __name__ == "__main__":
    sys.exit(main())
