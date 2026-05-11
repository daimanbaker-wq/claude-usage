"""
email_report.py - Generate and email the daily Claude usage report.

Usage:
  python3 email_report.py           # sends today + week + stats
  python3 email_report.py --dry-run # prints the email body without sending
"""

import sys
import smtplib
import subprocess
from datetime import date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / ".email_config"


def load_config():
    config = {}
    with open(CONFIG_FILE) as f:
        for line in f:
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                key, _, val = line.partition("=")
                config[key.strip()] = val.strip()
    return config


def run_cli(*args):
    result = subprocess.run(
        ["python3", str(Path(__file__).parent / "cli.py"), *args],
        capture_output=True, text=True
    )
    return result.stdout


def build_report():
    today = date.today().isoformat()

    # Scan first so data is current
    run_cli("scan")

    today_out = run_cli("today")
    week_out  = run_cli("week")
    stats_out = run_cli("stats")

    return f"""Claude API Usage Report — {today}
{"=" * 60}

{today_out.strip()}

{week_out.strip()}

{stats_out.strip()}
"""


def send_email(config, subject, body):
    import socket
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = config["FROM_EMAIL"]
    msg["To"]      = config["TO_EMAIL"]
    msg.attach(MIMEText(body, "plain"))

    # Resolve to IPv4 explicitly (some environments don't support IPv6)
    host = config["SMTP_HOST"]
    port = int(config["SMTP_PORT"])
    addr_info = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    ipv4_host = addr_info[0][4][0]

    with smtplib.SMTP(ipv4_host, port) as smtp:
        smtp.ehlo()
        smtp.starttls()          # upgrades the connection to TLS
        smtp.ehlo()
        smtp.login(config["FROM_EMAIL"], config["APP_PASSWORD"])
        smtp.sendmail(config["FROM_EMAIL"], config["TO_EMAIL"], msg.as_string())


def main():
    dry_run = "--dry-run" in sys.argv

    config = load_config()
    today  = date.today().isoformat()
    subject = f"Claude Usage Report — {today}"
    body   = build_report()

    if dry_run:
        print(f"Subject: {subject}")
        print(f"From:    {config['FROM_EMAIL']}")
        print(f"To:      {config['TO_EMAIL']}")
        print("-" * 60)
        print(body)
        return

    send_email(config, subject, body)
    print(f"Report sent to {config['TO_EMAIL']}")


if __name__ == "__main__":
    main()
