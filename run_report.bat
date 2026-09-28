@echo off
rem 保有株レポートを作成してブラウザで開く（最新データを取得してから作成）
chcp 65001 > nul
cd /d "%~dp0"
set PYTHONUTF8=1
python scripts\local_report.py --refresh
if errorlevel 1 pause
