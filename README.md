# Economic Indicators

日本株中心の市場ダッシュボード、保有株レポート、農業関連の先物、投資系 YouTuber の最新動画を、1つの Web アプリで見られます。
データは GitHub Actions が平日2回取得・分析し、GitHub Pages に配置します。

**公開ページ:** https://y-ookuma.github.io/Economic-Indicators/

## タブ

| タブ | 内容 |
|---|---|
| 市場 | 日本株・為替・金利・エネルギー／穀物先物・米国株・マクロ指標の最新値と推移 |
| 保有株レポート | 保有株 JSON を**ブラウザで読み込み**、損益・比率・トレンド・日経β・為替感応度・環境スコアを表示。「サマリー／銘柄別分析／銘柄を探す／判定ルール」に分かれる |
| 農業・先物 | 原油・暖房油（A重油の参考）・天然ガス（窒素肥料の参考）・穀物を、ドル建てと円換算で比較 |
| YouTuber | 登録チャンネルの最新動画タイトル（RSS、加工なし） |

## 保有株レポートの使い方

1. 「保有株レポート」タブで「ひな形をダウンロード」し、保有株を記入して `holdings.json` として保存する
2. ファイルをドラッグ＆ドロップ（または「ファイルを選ぶ」）
3. 「この端末のブラウザに保存する」にチェックしておくと、次回から自動で表示される

```json
{ "holdings": [ { "code": "7203", "name": "トヨタ自動車", "shares": 100, "avg_cost": 2800, "memo": "" } ] }
```

**プライバシー:** 保有 JSON はブラウザの中だけで処理され、送信されません。分析対象は日経225の全採用銘柄（＋ウォッチリスト）なので、公開データからどの銘柄を保有しているかは分かりません。
日経225以外の銘柄（ETF・中小型株など）は `config/watchlist.json` に追加してください。ここに書いた証券コードは公開されます（株数・取得単価は公開されません）。

## 構成

```
GitHub Actions（平日 JST 07:30 / 16:30、main への push 時）
  ├─ 公開中の data/*.json を取得（取得失敗時に前回値を使うため）
  ├─ scripts/fetch_data.py     … yfinance / FRED → data/indicators.json
  ├─ scripts/build_analysis.py … data/analysis.json（市場環境・先物・YouTuber）
  │                               data/stocks.json（日経225＋ウォッチリストの銘柄分析）
  └─ GitHub Pages に配置（データはコミットしない）
ブラウザ
  └─ index.html + js/*.js … data/*.json と、読み込んだ保有 JSON を突き合わせて表示
```

| パス | 役割 |
|---|---|
| `config/indicators.json` | 市場タブの指標の定義。**指標の追加・削除はここだけ編集すればよい** |
| `config/watchlist.json` | 日経225以外に分析する銘柄 |
| `config/youtubers.json` | YouTuber タブのチャンネル |
| `scripts/analysis.py` | 判定ルールと閾値（銘柄・市場環境・先物） |
| `js/report.js` | 保有株レポート。ポートフォリオの判定の閾値は先頭の定数 |
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

## FRED API キー（推奨）

FRED の公開 CSV は GitHub Actions からの接続に応答しないことがあります。無料の API キーを設定すると安定します。

1. https://fred.stlouisfed.org/docs/api/api_key.html でキーを取得
2. リポジトリの Settings → Secrets and variables → Actions → New repository secret で `FRED_API_KEY` を登録

## ローカルでの実行

```bash
pip install -r requirements.txt
python scripts/fetch_data.py
python scripts/build_analysis.py
python -m http.server 8000     # → http://localhost:8000
```

## 注意

- 表示内容は公開データから機械的に計算した状態の整理であり、将来の価格の予測や売買の推奨ではありません。環境スコアとその後のリターンの関係はまだ検証していません。
- yfinance は Yahoo Finance の非公式 API です。仕様変更で取得できなくなることがあるため、`requirements.txt` は定期的に更新してください。
- Yahoo のデータに時々混じる「数日だけ桁がずれた値」は自動で除去します（`remove_glitches`）。
- TOPIX は yfinance で取得できないため、連動ETF（1306.T）で代替しています。
- 日本CPI は FRED の月次系列の配信が終了したため、暫定で世界銀行の年次系列を使っています（e-Stat API に移行予定）。
- 日経225の構成銘柄は日経公式の CSV から銘柄コード・社名・業種のみ使用しています（ウエートは公開データに含めません）。
