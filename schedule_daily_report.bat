@echo off
:: Run this once as Administrator to register the daily Task Scheduler job.
:: It will run daily_report.py every day at 11:00 PM.

set TASK_NAME=ClaudeUsageDailyReport
set REPO_DIR=%~dp0
set BAT_FILE=%REPO_DIR%run_daily_report.bat

:: Create logs folder if it doesn't exist
if not exist "%REPO_DIR%logs" mkdir "%REPO_DIR%logs"

:: Delete existing task if it exists, then recreate
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "\"%BAT_FILE%\"" ^
  /sc daily ^
  /st 23:00 ^
  /rl highest ^
  /f

echo.
echo Task "%TASK_NAME%" registered successfully.
echo It will run every day at 11:00 PM.
echo.
echo To change the time, edit this file and update /st 23:00
echo To view logs: %REPO_DIR%logs\daily_report.log
echo To run manually now: python "%REPO_DIR%daily_report.py"
echo.
pause
