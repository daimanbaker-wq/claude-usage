"""
daily_report.py - Scan usage, write a dated file, and email the report.

Usage:
    python3 daily_report.py                     # scan + write file + email
    python3 daily_report.py --no-email          # scan + write file only
    python3 daily_report.py --send-only         # email existing file (no scan needed)
    python3 daily_report.py --to addr@example.com
    python3 daily_report.py --date 2026-05-07   # override date (used with --send-only)
"""

import io
import sys
import contextlib
from datetime import date
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


def read_usage_file(report_date: str) -> str:
    filename = Path(__file__).parent / f"Usage File for {report_date}"
    if not filename.exists():
        raise FileNotFoundError(
            f"No usage file found for {report_date}.\n"
            f"Expected: {filename}\n"
            f"Run without --send-only to generate it first."
        )
    return filename.read_text()


def parse_arg(args, flag):
    for i, arg in enumerate(args):
        if arg == flag and i + 1 < len(args):
            return args[i + 1]
    return None


def main():
    args = sys.argv[1:]
    send_only = "--send-only" in args
    send_email = "--no-email" not in args
    to_addr = parse_arg(args, "--to") or TO_ADDRESS
    report_date = parse_arg(args, "--date") or date.today().isoformat()

    print(f"\nClaude usage report for {report_date} ...")

    if send_only:
        # Just read the existing file and email it — no scanning required.
        # Useful when running from a machine that doesn't have the JSONL data.
        print("  Mode: send-only (reading existing usage file from repo)")
        report_text = read_usage_file(report_date)
    else:
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
