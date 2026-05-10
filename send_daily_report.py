"""
send_daily_report.py - Scan usage, save a dated report file, and email an HTML report with charts.

Configure the four constants below, then run:
  python3 send_daily_report.py

Schedule with launchd (macOS):
  See com.claude-usage.daily-report.plist in this repo.
"""

import os
import sys
import smtplib
import sqlite3
import base64
from io import BytesIO
from datetime import date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────
SMTP_USER   = "deebeemacmini@gmail.com"
SMTP_PASS   = "sjhm cyqb tiew tiak"
RECIPIENT   = "mydbhc@gmail.com"
REPORT_DIR  = Path(__file__).parent
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
    return str(int(n))

def short_model(name):
    return name.replace("claude-", "").replace("-2", "").strip()


def scan():
    sys.path.insert(0, str(Path(__file__).parent))
    from scanner import scan as do_scan
    do_scan()


def fetch_data(conn, today, week_start):
    today_rows = conn.execute("""
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

    by_day = conn.execute("""
        SELECT substr(timestamp,1,10) as day, COALESCE(model,'unknown') as model,
               SUM(input_tokens) as inp, SUM(output_tokens) as out,
               SUM(cache_read_tokens) as cr, SUM(cache_creation_tokens) as cc
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

    session_info = conn.execute("""
        SELECT COUNT(*) as sessions, MIN(first_timestamp) as first, MAX(last_timestamp) as last
        FROM sessions
    """).fetchone()

    top_projects = conn.execute("""
        SELECT COALESCE(s.project_name,'unknown') as project_name,
               SUM(t.input_tokens) as inp, SUM(t.output_tokens) as out,
               COUNT(*) as turns, COUNT(DISTINCT t.session_id) as sessions
        FROM turns t LEFT JOIN sessions s ON t.session_id=s.session_id
        GROUP BY s.project_name ORDER BY inp+out DESC LIMIT 5
    """).fetchall()

    return {
        "today_rows": today_rows,
        "sessions_today": sessions_today,
        "by_day": by_day,
        "by_model_week": by_model_week,
        "sessions_week": sessions_week,
        "totals": totals,
        "by_model_all": by_model_all,
        "session_info": session_info,
        "top_projects": top_projects,
    }


def make_chart_daily(data, today, week_start):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker

    start_d = date.fromisoformat(week_start)
    days = [(start_d + timedelta(days=i)).isoformat() for i in range(7)]
    labels = [(start_d + timedelta(days=i)).strftime("%a %-d") for i in range(7)]

    per_day = {d: 0.0 for d in days}
    for r in data["by_day"]:
        per_day[r["day"]] = per_day.get(r["day"], 0.0) + calc_cost(
            r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)

    costs = [per_day[d] for d in days]
    colors = ["#D0E8FF" if d != today else "#1A73E8" for d in days]

    fig, ax = plt.subplots(figsize=(7, 3.2))
    bars = ax.bar(labels, costs, color=colors, width=0.55, zorder=3)
    ax.set_facecolor("#F8FAFF")
    fig.patch.set_facecolor("#F8FAFF")
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f"${v:.2f}"))
    ax.set_ylabel("Estimated Cost (USD)", fontsize=9, color="#555")
    ax.set_title("Daily Cost — Last 7 Days", fontsize=11, fontweight="bold", color="#222", pad=10)
    ax.tick_params(colors="#555", labelsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#DDD")
    ax.spines["bottom"].set_color("#DDD")
    ax.yaxis.grid(True, color="#E0E0E0", linestyle="--", linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)

    for bar, cost in zip(bars, costs):
        if cost > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(costs) * 0.02,
                    f"${cost:.3f}", ha="center", va="bottom", fontsize=8, color="#333")

    plt.tight_layout()
    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def make_chart_models(data):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = data["by_model_week"]
    if not rows:
        return None

    labels = [short_model(r["model"]) for r in rows]
    inp_vals = [r["inp"] or 0 for r in rows]
    out_vals = [r["out"] or 0 for r in rows]

    x = range(len(labels))
    width = 0.38

    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.set_facecolor("#F8FAFF")
    fig.patch.set_facecolor("#F8FAFF")

    b1 = ax.bar([i - width / 2 for i in x], inp_vals, width, label="Input tokens",
                color="#1A73E8", zorder=3)
    b2 = ax.bar([i + width / 2 for i in x], out_vals, width, label="Output tokens",
                color="#34A853", zorder=3)

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=9, color="#555")
    ax.set_title("Token Usage by Model — This Week", fontsize=11, fontweight="bold", color="#222", pad=10)
    ax.set_ylabel("Tokens", fontsize=9, color="#555")
    ax.tick_params(colors="#555", labelsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#DDD")
    ax.spines["bottom"].set_color("#DDD")
    ax.yaxis.grid(True, color="#E0E0E0", linestyle="--", linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(fontsize=8, framealpha=0.5)

    plt.tight_layout()
    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def build_html(today, week_start, data):
    d = data

    # Totals for today
    tot_cost = sum(calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
                   for r in d["today_rows"])
    tot_turns = sum(r["turns"] for r in d["today_rows"])
    tot_inp = sum(r["inp"] or 0 for r in d["today_rows"])
    tot_out = sum(r["out"] or 0 for r in d["today_rows"])
    tot_cr  = sum(r["cr"]  or 0 for r in d["today_rows"])
    tot_cc  = sum(r["cc"]  or 0 for r in d["today_rows"])

    # All-time cost
    all_cost = sum(calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
                   for r in d["by_model_all"])

    # Charts
    chart_daily  = make_chart_daily(data, today, week_start)
    chart_models = make_chart_models(data)

    chart_daily_tag = f'<img src="data:image/png;base64,{chart_daily}" style="width:100%;max-width:640px;border-radius:8px;" alt="Daily cost chart">'
    chart_models_tag = (f'<img src="data:image/png;base64,{chart_models}" style="width:100%;max-width:640px;border-radius:8px;" alt="Model usage chart">'
                        if chart_models else "<p style='color:#888'>No model data this week.</p>")

    def stat_card(label, value, sub=""):
        return f"""
        <td style="text-align:center;padding:12px 20px;background:#fff;border-radius:10px;
                   box-shadow:0 1px 4px rgba(0,0,0,0.08);min-width:110px;">
          <div style="font-size:22px;font-weight:700;color:#1A73E8;">{value}</div>
          <div style="font-size:11px;color:#888;margin-top:2px;text-transform:uppercase;letter-spacing:.5px;">{label}</div>
          {f'<div style="font-size:10px;color:#aaa;margin-top:1px;">{sub}</div>' if sub else ''}
        </td>"""

    def model_rows_today():
        if not d["today_rows"]:
            return '<tr><td colspan="5" style="color:#999;text-align:center;padding:12px;">No activity today.</td></tr>'
        rows = ""
        for r in d["today_rows"]:
            cost = calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
            rows += f"""
            <tr>
              <td style="padding:8px 12px;color:#333;">{r['model']}</td>
              <td style="padding:8px 12px;text-align:center;color:#555;">{r['turns']}</td>
              <td style="padding:8px 12px;text-align:right;color:#555;">{fmt(r['inp'] or 0)}</td>
              <td style="padding:8px 12px;text-align:right;color:#555;">{fmt(r['out'] or 0)}</td>
              <td style="padding:8px 12px;text-align:right;font-weight:600;color:#1A73E8;">${cost:.4f}</td>
            </tr>"""
        return rows

    def alltime_rows():
        rows = ""
        for r in d["by_model_all"]:
            cost = calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
            rows += f"""
            <tr>
              <td style="padding:8px 12px;color:#333;">{r['model']}</td>
              <td style="padding:8px 12px;text-align:center;color:#555;">{r['sessions']}</td>
              <td style="padding:8px 12px;text-align:center;color:#555;">{fmt(r['turns'] or 0)}</td>
              <td style="padding:8px 12px;text-align:right;color:#555;">{fmt(r['inp'] or 0)}</td>
              <td style="padding:8px 12px;text-align:right;color:#555;">{fmt(r['out'] or 0)}</td>
              <td style="padding:8px 12px;text-align:right;font-weight:600;color:#1A73E8;">${cost:.4f}</td>
            </tr>"""
        return rows

    th = "padding:8px 12px;background:#F0F4FF;color:#555;font-size:11px;text-transform:uppercase;letter-spacing:.5px;font-weight:600;"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#F0F4FF;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F0F4FF;padding:30px 0;">
<tr><td align="center">
<table width="660" cellpadding="0" cellspacing="0" style="max-width:660px;width:100%;">

  <!-- Header -->
  <tr><td style="background:linear-gradient(135deg,#1A73E8 0%,#0D47A1 100%);
                 border-radius:12px 12px 0 0;padding:28px 32px;">
    <div style="color:#fff;font-size:22px;font-weight:700;letter-spacing:-.3px;">
      Claude Code Usage Report
    </div>
    <div style="color:rgba(255,255,255,0.75);font-size:13px;margin-top:4px;">
      {date.fromisoformat(today).strftime("%A, %B %-d, %Y")}
    </div>
  </td></tr>

  <!-- Body -->
  <tr><td style="background:#fff;padding:28px 32px;border-radius:0 0 12px 12px;
                 box-shadow:0 2px 12px rgba(0,0,0,0.08);">

    <!-- Stat cards -->
    <div style="font-size:13px;font-weight:600;color:#888;text-transform:uppercase;
                letter-spacing:.6px;margin-bottom:14px;">Today at a Glance</div>
    <table cellpadding="0" cellspacing="10" style="border-collapse:separate;margin-bottom:28px;">
      <tr>
        {stat_card("Est. Cost", f"${tot_cost:.4f}", "today")}
        {stat_card("Turns", str(tot_turns), "today")}
        {stat_card("Sessions", str(d['sessions_today']), "today")}
        {stat_card("Output Tokens", fmt(tot_out), "today")}
        {stat_card("All-Time Cost", f"${all_cost:.4f}", "total")}
      </tr>
    </table>

    <!-- Daily chart -->
    <div style="font-size:13px;font-weight:600;color:#888;text-transform:uppercase;
                letter-spacing:.6px;margin-bottom:12px;">Weekly Cost Trend</div>
    <div style="background:#F8FAFF;border-radius:10px;padding:16px;margin-bottom:28px;text-align:center;">
      {chart_daily_tag}
    </div>

    <!-- Model chart -->
    <div style="font-size:13px;font-weight:600;color:#888;text-transform:uppercase;
                letter-spacing:.6px;margin-bottom:12px;">Token Usage by Model</div>
    <div style="background:#F8FAFF;border-radius:10px;padding:16px;margin-bottom:28px;text-align:center;">
      {chart_models_tag}
    </div>

    <!-- Today's table -->
    <div style="font-size:13px;font-weight:600;color:#888;text-transform:uppercase;
                letter-spacing:.6px;margin-bottom:12px;">Today's Usage by Model</div>
    <table width="100%" cellpadding="0" cellspacing="0"
           style="border-collapse:collapse;margin-bottom:28px;border-radius:8px;overflow:hidden;border:1px solid #E8EEF8;">
      <tr>
        <th style="{th}text-align:left;">Model</th>
        <th style="{th}text-align:center;">Turns</th>
        <th style="{th}text-align:right;">Input</th>
        <th style="{th}text-align:right;">Output</th>
        <th style="{th}text-align:right;">Cost</th>
      </tr>
      {model_rows_today()}
      <tr style="border-top:2px solid #E8EEF8;">
        <td style="padding:8px 12px;font-weight:700;color:#222;">Total</td>
        <td style="padding:8px 12px;text-align:center;font-weight:700;color:#222;">{tot_turns}</td>
        <td style="padding:8px 12px;text-align:right;font-weight:700;color:#222;">{fmt(tot_inp)}</td>
        <td style="padding:8px 12px;text-align:right;font-weight:700;color:#222;">{fmt(tot_out)}</td>
        <td style="padding:8px 12px;text-align:right;font-weight:700;color:#1A73E8;">${tot_cost:.4f}</td>
      </tr>
      <tr><td colspan="5" style="padding:6px 12px;background:#FAFBFF;font-size:11px;color:#aaa;">
        Cache read: {fmt(tot_cr)} &nbsp;·&nbsp; Cache creation: {fmt(tot_cc)}
      </td></tr>
    </table>

    <!-- All-time table -->
    <div style="font-size:13px;font-weight:600;color:#888;text-transform:uppercase;
                letter-spacing:.6px;margin-bottom:12px;">All-Time Statistics</div>
    <table width="100%" cellpadding="0" cellspacing="0"
           style="border-collapse:collapse;margin-bottom:16px;border-radius:8px;overflow:hidden;border:1px solid #E8EEF8;">
      <tr>
        <th style="{th}text-align:left;">Model</th>
        <th style="{th}text-align:center;">Sessions</th>
        <th style="{th}text-align:center;">Turns</th>
        <th style="{th}text-align:right;">Input</th>
        <th style="{th}text-align:right;">Output</th>
        <th style="{th}text-align:right;">Cost</th>
      </tr>
      {alltime_rows()}
      <tr style="border-top:2px solid #E8EEF8;">
        <td colspan="2" style="padding:8px 12px;font-weight:700;color:#222;">
          Total &nbsp;<span style="font-size:11px;color:#aaa;font-weight:400;">
          ({(d['session_info']['first'] or '')[:10]} – {(d['session_info']['last'] or '')[:10]})</span>
        </td>
        <td style="padding:8px 12px;text-align:center;font-weight:700;color:#222;">
          {fmt(d['totals']['turns'] or 0)}
        </td>
        <td style="padding:8px 12px;text-align:right;font-weight:700;color:#222;">
          {fmt(d['totals']['inp'] or 0)}
        </td>
        <td style="padding:8px 12px;text-align:right;font-weight:700;color:#222;">
          {fmt(d['totals']['out'] or 0)}
        </td>
        <td style="padding:8px 12px;text-align:right;font-weight:700;color:#1A73E8;">
          ${all_cost:.4f}
        </td>
      </tr>
    </table>

  </td></tr>

  <!-- Footer -->
  <tr><td style="text-align:center;padding:16px;color:#aaa;font-size:11px;">
    Generated by claude-usage &nbsp;·&nbsp; {today}
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""
    return html


def build_plain(today, week_start, data):
    d = data
    lines = [f"Claude Code Usage Report — {today}", "=" * 60]

    tot_cost = sum(calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
                   for r in d["today_rows"])
    tot_turns = sum(r["turns"] for r in d["today_rows"])

    lines += ["", f"TODAY  |  turns: {tot_turns}  cost: ${tot_cost:.4f}  sessions: {d['sessions_today']}"]
    for r in d["today_rows"]:
        cost = calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
        lines.append(f"  {r['model']:<30}  turns={r['turns']}  in={fmt(r['inp'] or 0)}  out={fmt(r['out'] or 0)}  cost=${cost:.4f}")

    lines += ["", "-" * 60, "WEEKLY (last 7 days)"]
    start_d = date.fromisoformat(week_start)
    per_day = {}
    for r in d["by_day"]:
        b = per_day.setdefault(r["day"], {"turns": 0, "inp": 0, "out": 0, "cost": 0.0})
        b["cost"] += calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
        b["inp"]  += r["inp"] or 0
        b["out"]  += r["out"] or 0

    for i in range(7):
        d2 = (start_d + timedelta(days=i)).isoformat()
        b = per_day.get(d2, {"cost": 0.0, "inp": 0, "out": 0})
        lines.append(f"  {d2}  in={fmt(b['inp']):<8}  out={fmt(b['out']):<8}  cost=${b['cost']:.4f}")

    all_cost = sum(calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
                   for r in d["by_model_all"])
    lines += ["", "-" * 60, f"ALL-TIME  |  sessions: {d['session_info']['sessions']}  "
              f"turns: {fmt(d['totals']['turns'] or 0)}  cost: ${all_cost:.4f}"]
    return "\n".join(lines)


def save_report(today, content):
    path = REPORT_DIR / f"Usage File for {today}"
    path.write_text(content)
    print(f"Report saved: {path}")


def send_email(today, html, plain):
    msg = MIMEMultipart("alternative")
    msg["From"]    = SMTP_USER
    msg["To"]      = RECIPIENT
    msg["Subject"] = f"Claude API Usage Report — {today}"
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html,  "html"))

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

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print("Building report...")
    data  = fetch_data(conn, today, week_start)
    html  = build_html(today, week_start, data)
    plain = build_plain(today, week_start, data)
    conn.close()

    save_report(today, plain)
    send_email(today, html, plain)


if __name__ == "__main__":
    main()
