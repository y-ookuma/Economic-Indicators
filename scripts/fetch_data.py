"""経済指標・株価データを取得して data/indicators.json を生成する。

データ源（いずれも API キー不要）:
  - yfinance : 株価指数・為替・金利・商品（日次）
  - FRED     : マクロ経済指標（fredgraph.csv の公開エンドポイント）

使い方:
  pip install -r requirements.txt
  python scripts/fetch_data.py
"""

from __future__ import annotations

import io
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "indicators.json"
OUTPUT_PATH = ROOT / "data" / "indicators.json"

MARKET_PERIOD = "5y"          # yfinance の取得期間
MACRO_START = "2000-01-01"    # FRED の取得開始日
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def remove_glitches(s: pd.Series, jump: float = 0.5, max_len: int = 5, tol: float = 0.1) -> pd.Series:
    """Yahoo のデータに時々混じる「数日だけ桁がずれた値」を除く。

    対数変化が ±jump を超えて跳び、max_len 営業日以内にほぼ同じ幅（誤差 tol）で
    逆方向に戻る区間だけを異常値とみなす。実際の急騰・急落（戻らないもの）は残す。
    """
    s = s[s > 0]
    r = np.log(s).diff().to_numpy()
    drop = np.zeros(len(s), dtype=bool)
    i = 1
    while i < len(s):
        if abs(r[i]) > jump:
            for j in range(i + 1, min(i + 1 + max_len, len(s))):
                if abs(r[i] + r[j]) < tol and abs(r[j]) > jump:
                    drop[i:j] = True
                    i = j
                    break
        i += 1
    if drop.any():
        print(f"     removed {drop.sum()} glitch point(s): {list(s.index[drop].strftime('%Y-%m-%d'))}")
    return s[~drop]


def fetch_yfinance(ticker: str, period: str = MARKET_PERIOD) -> pd.Series:
    df = yf.download(ticker, period=period, interval="1d",
                     auto_adjust=False, progress=False, threads=False)
    if df.empty:
        raise ValueError(f"no data for {ticker}")
    close = df["Close"]
    if isinstance(close, pd.DataFrame):  # 新しい yfinance は MultiIndex 列を返す
        close = close.iloc[:, 0]
    return remove_glitches(close.dropna())


def fetch_fred(series_id: str) -> pd.Series:
    resp = requests.get(FRED_CSV_URL, params={"id": series_id, "cosd": MACRO_START},
                        timeout=30, headers={"User-Agent": "Economic-Indicators/1.0"})
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    date_col, value_col = df.columns[0], df.columns[1]
    s = pd.Series(pd.to_numeric(df[value_col], errors="coerce").values,
                  index=pd.to_datetime(df[date_col]))
    return s.dropna()


def apply_transform(s: pd.Series, transform: str | None) -> pd.Series:
    if transform == "yoy":
        # 月次=12期前、四半期=4期前と比較
        freq = pd.infer_freq(s.index[-24:]) or "M"
        lag = 4 if freq.startswith("Q") else 12
        return (s / s.shift(lag) - 1).mul(100).dropna()
    if transform == "diff":
        return s.diff().dropna()
    return s


def summarize(s: pd.Series, decimals: int) -> dict:
    digits = max(decimals, 2) + 2  # 保存精度は表示桁より少し多めに
    history = [[d.strftime("%Y-%m-%d"), round(float(v), digits)]
               for d, v in s.items() if not math.isnan(v)]
    latest, prev = history[-1], history[-2] if len(history) > 1 else None
    change = None
    if prev:
        abs_chg = latest[1] - prev[1]
        pct_chg = abs_chg / prev[1] * 100 if prev[1] else None
        change = {"prev_date": prev[0], "abs": round(abs_chg, digits),
                  "pct": round(pct_chg, 3) if pct_chg is not None else None}
    return {"latest": {"date": latest[0], "value": latest[1]},
            "change": change, "history": history}


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    series_out: dict[str, dict] = {}
    errors: dict[str, str] = {}

    for key, ind in config["indicators"].items():
        try:
            if ind["source"] == "yfinance":
                s = fetch_yfinance(ind["ticker"])
            elif ind["source"] == "fred":
                s = fetch_fred(ind["series_id"])
            else:
                raise ValueError(f"unknown source {ind['source']}")
            s = apply_transform(s, ind.get("transform"))
            meta = {k: v for k, v in ind.items() if k != "_comment"}
            series_out[key] = {**meta, **summarize(s, ind.get("decimals", 2))}
            print(f"OK   {key:12s} {series_out[key]['latest']}")
        except Exception as e:  # 1指標の失敗で全体を止めない
            errors[key] = f"{type(e).__name__}: {e}"
            print(f"FAIL {key:12s} {errors[key]}", file=sys.stderr)

    # 取得に失敗した指標は前回のデータを残す
    if errors and OUTPUT_PATH.exists():
        previous = json.loads(OUTPUT_PATH.read_text(encoding="utf-8")).get("series", {})
        for key in errors:
            if key in previous:
                series_out[key] = {**previous[key], "stale": True}

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "groups": config["groups"],
        "series": series_out,
        "errors": errors,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")),
                           encoding="utf-8")
    print(f"\nwrote {OUTPUT_PATH.relative_to(ROOT)}  ok={len(series_out)} failed={len(errors)}")
    # 全滅した場合のみ失敗扱い（Actions で気づけるように）
    return 1 if not series_out else 0


if __name__ == "__main__":
    sys.exit(main())
