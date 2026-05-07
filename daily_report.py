"""
daily_report.py - Scan usage, write a dated file, and email the report.

Usage:
    python3 daily_report.py
    python3 daily_report.py --to mydbhc@gmail.com
    python3 daily_report.py --no-email       # write file only
"""

import io
import sys
import contextlib
from datetime import date, timedelta
from pathlib import Path


TO_ADDRESS = "mydbhc@gmail.com"


def capture(fn, *args, **kwargs) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kwargs)
    return buf.getvalue()


def build_report(report_date: str) -> str:
    import cli
    from scanner import scan

    # Always scan first so data is fresh
    scan()

    today_text = capture(cli.cmd_today)
    week_text = capture(cli.cmd_week)
    stats_text = capture(cli.cmd_stats)

    return (
        f"Claude API Usage Report — {report_date}\n"
        "=" * 60 + "\n\n"
        "TODAY\n" + today_text +
        "LAST 7 DAYS\n" + week_text +
        "ALL-TIME STATS\n" + stats_text
    )


def write_usage_file(report_text: str, report_date: str) -> Path:
    filename = Path(__file__).parent / f"Usage File for {report_date}"
    filename.write_text(report_text)
    print(f"  Usage file written: {filename.name}")
    return filename


def main():
    send_email = "--no-email" not in sys.argv
    to_addr = TO_ADDRESS
    for i, arg in enumerate(sys.argv):
        if arg == "--to" and i + 1 < len(sys.argv):
            to_addr = sys.argv[i + 1]

    report_date = date.today().isoformat()
    print(f"\nGenerating Claude usage report for {report_date} ...")

    report_text = build_report(report_date)
    write_usage_file(report_text, report_date)

    if send_email:
        from emailer import send_report
        send_report(report_text, to_addr, report_date)
    else:
        print("  Email skipped (--no-email).")

    print("Done.\n")


if __name__ == "__main__":
    main()
