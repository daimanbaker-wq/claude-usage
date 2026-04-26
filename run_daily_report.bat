@echo off
cd /d "%~dp0"
python daily_report.py >> logs\daily_report.log 2>&1
