# Economic Indicators

日米の株価・為替・金利・マクロ経済指標を一覧できるダッシュボードです。
GitHub Actions が定期的にデータを取得し、GitHub Pages で表示します。

**公開ページ:** https://y-ookuma.github.io/Economic-Indicators/

## 構成

```
GitHub Actions（平日2回）
  └─ scripts/fetch_data.py ── yfinance / FRED ──▶ data/indicators.json（コミット）
GitHub Pages
  └─ index.html + js/app.js ── data/indicators.json を読んで表示
```

| パス | 役割 |
|---|---|
| `config/indicators.json` | 取得する指標の定義。**指標の追加・削除はここだけ編集すればよい** |
| `scripts/fetch_data.py` | データを取得して `data/indicators.json` を生成する |
| `data/indicators.json` | 生成されたデータ（Actions が自動で更新） |
| `index.html`, `css/`, `js/` | ダッシュボード画面 |
| `.github/workflows/update-data.yml` | 定期実行（JST 07:30 / 16:30、平日） |
| `docs/EIM_design.md` | 経済影響モデル（EIM）の全体設計 |

## 指標の追加方法

`config/indicators.json` の `indicators` に項目を追加し、`groups` の `items` にキーを入れます。

```jsonc
// yfinance（ティッカーは Yahoo Finance で確認）
"toyota": { "name": "トヨタ", "source": "yfinance", "ticker": "7203.T", "unit": "円", "decimals": 0, "polarity": 1 }
// FRED（series_id は https://fred.stlouisfed.org で確認）
"us_m2":  { "name": "米M2", "source": "fred", "series_id": "M2SL", "transform": "yoy", "unit": "%", "decimals": 1, "polarity": 0 }
```

- `transform`: `none`（そのまま）/ `yoy`（前年同期比 %）/ `diff`（前期差）
- `polarity`: `1` 上昇が好材料、`-1` 上昇が悪材料、`0` 中立。前回比の色分けに使います

## ローカルでの実行

```bash
pip install -r requirements.txt
python scripts/fetch_data.py
python -m http.server 8000     # → http://localhost:8000
```

## 注意

- yfinance は Yahoo Finance の非公式APIです。仕様変更で取得できなくなることがあるため、`requirements.txt` は定期的に更新してください。取得に失敗した指標は前回のデータを残し、「⚠ 未更新」と表示します。
- TOPIX は yfinance で取得できないため、連動ETF（1306.T）で代替しています。
- 日本CPI は FRED の月次系列の配信が終了したため、暫定で世界銀行の年次系列を使っています（e-Stat API に移行予定）。
