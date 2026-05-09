"""
send_daily_report.py - Scan usage, save a dated report file, and email it.

Configure the four constants below, then run:
  python3 send_daily_report.py

Schedule with launchd (macOS):
  See com.claude-usage.daily-report.plist in this repo.
"""

import os
import sys
import smtplib
import sqlite3
from datetime import date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────
SMTP_USER   = "deebeemacmini@gmail.com"
SMTP_PASS   = "sjhm cyqb tiew tiak"
RECIPIENT   = "mydbhc@gmail.com"
REPORT_DIR  = Path(__file__).parent   # folder where report files are saved
# ─────────────────────────────────────────────────────────────────────────────

DB_PATH = Path.home() / ".claude" / "usage.db"

PRICING = {
    "claude-opus-4-7":   {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-6":   {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-5":   {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-sonnet-4-7": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-haiku-4-7":  {"input": 1.00, "output":  5.00, "cache_read": 0.10, "cache_write": 1.25},
    "claude-haiku-4-6":  {"input": 1.00, "output":  5.00, "cache_read": 0.10, "cache_write": 1.25},
    "claude-haiku-4-5":  {"input": 1.00, "output":  5.00, "cache_read": 0.10, "cache_write": 1.25},
}

def get_pricing(model):
    if not model:
        return None
    if model in PRICING:
        return PRICING[model]
    for key in PRICING:
        if model.startswith(key):
            return PRICING[key]
    m = model.lower()
    if "opus"   in m: return PRICING["claude-opus-4-7"]
    if "sonnet" in m: return PRICING["claude-sonnet-4-6"]
    if "haiku"  in m: return PRICING["claude-haiku-4-5"]
    return None

def calc_cost(model, inp, out, cr, cc):
    p = get_pricing(model)
    if not p:
        return 0.0
    return (inp * p["input"] + out * p["output"] +
            cr  * p["cache_read"] + cc * p["cache_write"]) / 1_000_000

def fmt(n):
    if n >= 1_000_000: return f"{n/1_000_000:.2f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}K"
    return str(n)

def fmt_cost(c):
    return f"${c:.4f}"


def scan():
    repo_dir = Path(__file__).parent
    sys.path.insert(0, str(repo_dir))
    from scanner import scan as do_scan
    do_scan()


def build_report(today: str, week_start: str) -> str:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    lines = []

    def h(char="-", w=60): lines.append(char * w)

    # ── Today ──
    rows = conn.execute("""
        SELECT COALESCE(model,'unknown') as model,
               SUM(input_tokens) as inp, SUM(output_tokens) as out,
               SUM(cache_read_tokens) as cr, SUM(cache_creation_tokens) as cc,
               COUNT(*) as turns
        FROM turns WHERE substr(timestamp,1,10)=?
        GROUP BY model ORDER BY inp+out DESC
    """, (today,)).fetchall()

    sessions_today = conn.execute("""
        SELECT COUNT(DISTINCT session_id) as cnt FROM turns
        WHERE substr(timestamp,1,10)=?
    """, (today,)).fetchone()["cnt"]

    lines.append(f"Claude Code Usage Report")
    lines.append(f"Generated: {today}")
    h("=")
    lines.append(f"")
    lines.append(f"TODAY'S USAGE ({today})")
    h()
    lines.append(f"{'Model':<32} {'Turns':>5}  {'Input':>8}  {'Output':>8}  {'Cost':>10}")
    h()

    tot_inp = tot_out = tot_cr = tot_cc = tot_turns = 0
    tot_cost = 0.0
    if rows:
        for r in rows:
            cost = calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
            tot_cost  += cost
            tot_inp   += r["inp"] or 0
            tot_out   += r["out"] or 0
            tot_cr    += r["cr"]  or 0
            tot_cc    += r["cc"]  or 0
            tot_turns += r["turns"]
            lines.append(f"  {r['model']:<30} {r['turns']:>5}  {fmt(r['inp'] or 0):>8}  {fmt(r['out'] or 0):>8}  {fmt_cost(cost):>10}")
    else:
        lines.append("  No usage recorded today.")

    h()
    lines.append(f"  {'TOTAL':<30} {tot_turns:>5}  {fmt(tot_inp):>8}  {fmt(tot_out):>8}  {fmt_cost(tot_cost):>10}")
    lines.append(f"")
    lines.append(f"  Sessions today:   {sessions_today}")
    lines.append(f"  Cache read:       {fmt(tot_cr)}")
    lines.append(f"  Cache creation:   {fmt(tot_cc)}")

    # ── Week ──
    by_day_model = conn.execute("""
        SELECT substr(timestamp,1,10) as day, COALESCE(model,'unknown') as model,
               SUM(input_tokens) as inp, SUM(output_tokens) as out,
               SUM(cache_read_tokens) as cr, SUM(cache_creation_tokens) as cc,
               COUNT(*) as turns
        FROM turns WHERE substr(timestamp,1,10) BETWEEN ? AND ?
        GROUP BY day, model
    """, (week_start, today)).fetchall()

    by_model_week = conn.execute("""
        SELECT COALESCE(model,'unknown') as model,
               SUM(input_tokens) as inp, SUM(output_tokens) as out,
               SUM(cache_read_tokens) as cr, SUM(cache_creation_tokens) as cc,
               COUNT(*) as turns
        FROM turns WHERE substr(timestamp,1,10) BETWEEN ? AND ?
        GROUP BY model ORDER BY inp+out DESC
    """, (week_start, today)).fetchall()

    sessions_week = conn.execute("""
        SELECT COUNT(DISTINCT session_id) as cnt FROM turns
        WHERE substr(timestamp,1,10) BETWEEN ? AND ?
    """, (week_start, today)).fetchone()["cnt"]

    per_day = {}
    for r in by_day_model:
        b = per_day.setdefault(r["day"], {"turns": 0, "inp": 0, "out": 0, "cost": 0.0})
        b["turns"] += r["turns"]
        b["inp"]   += r["inp"] or 0
        b["out"]   += r["out"] or 0
        b["cost"]  += calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)

    lines.append(f"")
    lines.append(f"WEEKLY USAGE ({week_start} to {today})")
    h()
    lines.append("  By Day:")
    start_d = date.fromisoformat(week_start)
    for i in range(7):
        d = (start_d + timedelta(days=i)).isoformat()
        b = per_day.get(d, {"turns": 0, "inp": 0, "out": 0, "cost": 0.0})
        lines.append(f"    {d}  turns={b['turns']:<4}  in={fmt(b['inp']):<8}  out={fmt(b['out']):<8}  cost={fmt_cost(b['cost'])}")

    h()
    lines.append("  By Model:")
    wk_inp = wk_out = wk_cr = wk_cc = wk_turns = 0
    wk_cost = 0.0
    for r in by_model_week:
        cost = calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
        wk_cost  += cost
        wk_inp   += r["inp"] or 0
        wk_out   += r["out"] or 0
        wk_cr    += r["cr"]  or 0
        wk_cc    += r["cc"]  or 0
        wk_turns += r["turns"]
        lines.append(f"    {r['model']:<30}  turns={r['turns']:<4}  in={fmt(r['inp'] or 0):<8}  out={fmt(r['out'] or 0):<8}  cost={fmt_cost(cost)}")
    h()
    lines.append(f"    {'TOTAL':<30}  turns={wk_turns:<4}  in={fmt(wk_inp):<8}  out={fmt(wk_out):<8}  cost={fmt_cost(wk_cost)}")
    lines.append(f"")
    lines.append(f"  Sessions this week:  {sessions_week}")
    lines.append(f"  Cache read:          {fmt(wk_cr)}")
    lines.append(f"  Cache creation:      {fmt(wk_cc)}")

    # ── All-time ──
    session_info = conn.execute("""
        SELECT COUNT(*) as sessions, MIN(first_timestamp) as first, MAX(last_timestamp) as last
        FROM sessions
    """).fetchone()

    totals = conn.execute("""
        SELECT SUM(input_tokens) as inp, SUM(output_tokens) as out,
               SUM(cache_read_tokens) as cr, SUM(cache_creation_tokens) as cc,
               COUNT(*) as turns
        FROM turns
    """).fetchone()

    by_model_all = conn.execute("""
        SELECT COALESCE(model,'unknown') as model,
               SUM(input_tokens) as inp, SUM(output_tokens) as out,
               SUM(cache_read_tokens) as cr, SUM(cache_creation_tokens) as cc,
               COUNT(*) as turns, COUNT(DISTINCT session_id) as sessions
        FROM turns GROUP BY model ORDER BY inp+out DESC
    """).fetchall()

    top_projects = conn.execute("""
        SELECT COALESCE(s.project_name,'unknown') as project_name,
               SUM(t.input_tokens) as inp, SUM(t.output_tokens) as out,
               COUNT(*) as turns, COUNT(DISTINCT t.session_id) as sessions
        FROM turns t LEFT JOIN sessions s ON t.session_id=s.session_id
        GROUP BY s.project_name ORDER BY inp+out DESC LIMIT 5
    """).fetchall()

    daily_avg = conn.execute("""
        SELECT AVG(daily_inp) as avg_inp, AVG(daily_out) as avg_out FROM (
            SELECT substr(timestamp,1,10) as day,
                   SUM(input_tokens) as daily_inp, SUM(output_tokens) as daily_out
            FROM turns WHERE timestamp >= datetime('now','-30 days')
            GROUP BY day)
    """).fetchone()

    all_cost = sum(calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
                   for r in by_model_all)

    lines.append(f"")
    lines.append(f"ALL-TIME STATISTICS")
    h("=")
    lines.append(f"  Period:           {(session_info['first'] or '')[:10]} to {(session_info['last'] or '')[:10]}")
    lines.append(f"  Total sessions:   {session_info['sessions'] or 0:,}")
    lines.append(f"  Total turns:      {fmt(totals['turns'] or 0)}")
    lines.append(f"")
    lines.append(f"  Input tokens:     {fmt(totals['inp'] or 0):<12}  (raw prompt tokens)")
    lines.append(f"  Output tokens:    {fmt(totals['out'] or 0):<12}  (generated tokens)")
    lines.append(f"  Cache read:       {fmt(totals['cr'] or 0):<12}  (90% cheaper than input)")
    lines.append(f"  Cache creation:   {fmt(totals['cc'] or 0):<12}  (25% premium on input)")
    lines.append(f"")
    lines.append(f"  Est. total cost:  ${all_cost:.4f}")
    h()
    lines.append("  By Model:")
    for r in by_model_all:
        cost = calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
        lines.append(f"    {r['model']:<30}  sessions={r['sessions']:<4}  turns={fmt(r['turns'] or 0):<6}  "
                     f"in={fmt(r['inp'] or 0):<8}  out={fmt(r['out'] or 0):<8}  cost={fmt_cost(cost)}")
    h()
    lines.append("  Top Projects:")
    for r in top_projects:
        lines.append(f"    {(r['project_name'] or 'unknown'):<40}  sessions={r['sessions']:<3}  "
                     f"turns={fmt(r['turns'] or 0):<6}  tokens={fmt((r['inp'] or 0)+(r['out'] or 0))}")
    if daily_avg["avg_inp"]:
        h()
        lines.append("  Daily Average (last 30 days):")
        lines.append(f"    Input:   {fmt(int(daily_avg['avg_inp'] or 0))}")
        lines.append(f"    Output:  {fmt(int(daily_avg['avg_out'] or 0))}")
    h("=")

    conn.close()
    return "\n".join(lines)


def save_report(today: str, content: str) -> Path:
    path = REPORT_DIR / f"Usage File for {today}"
    path.write_text(content)
    print(f"Report saved: {path}")
    return path


def send_email(today: str, content: str):
    msg = MIMEMultipart()
    msg["From"]    = SMTP_USER
    msg["To"]      = RECIPIENT
    msg["Subject"] = f"Claude API Usage Report — {today}"
    msg.attach(MIMEText(content, "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.ehlo()
        s.starttls()
        s.ehlo()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_USER, RECIPIENT, msg.as_string())
    print(f"Email sent to {RECIPIENT}")


def main():
    today      = date.today().isoformat()
    week_start = (date.today() - timedelta(days=6)).isoformat()

    print("Scanning usage logs...")
    scan()

    print("Building report...")
    report = build_report(today, week_start)

    save_report(today, report)
    send_email(today, report)


if __name__ == "__main__":
    main()
