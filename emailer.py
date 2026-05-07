"""
emailer.py - Send Claude usage reports via Gmail SMTP.

Reads credentials from .env (GMAIL_USER, GMAIL_APP_PASSWORD) or environment.
"""

import os
import socket
import smtplib
import ssl
from datetime import date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path


def _load_env():
    """Load .env file from the repo root into os.environ if present."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def get_credentials():
    _load_env()
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not user or not password:
        raise RuntimeError(
            "Missing credentials. Set GMAIL_USER and GMAIL_APP_PASSWORD in .env "
            "or as environment variables."
        )
    return user, password


def send_report(report_text: str, to_addr: str, report_date: str = None):
    """Send a plain-text usage report email via Gmail SMTP."""
    from_addr, app_password = get_credentials()
    report_date = report_date or date.today().isoformat()

    subject = f"Claude API Usage Report — {report_date}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(report_text, "plain"))

    # Resolve to IPv4 explicitly — IPv6 is not available in this environment
    ipv4 = socket.getaddrinfo("smtp.gmail.com", 587, socket.AF_INET)[0][4][0]
    context = ssl.create_default_context()
    with smtplib.SMTP(ipv4, 587) as server:
        server.ehlo("smtp.gmail.com")
        server.starttls(context=context)
        server.ehlo("smtp.gmail.com")
        server.login(from_addr, app_password)
        server.sendmail(from_addr, to_addr, msg.as_string())

    print(f"  Email sent: {from_addr} -> {to_addr}  (subject: {subject})")
