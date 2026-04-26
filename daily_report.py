"""
daily_report.py - Run daily: scans usage, creates text report, generates
combined graph PNG, commits and pushes to git.

Usage:
  python daily_report.py
  python daily_report.py --no-push   (skip git commit/push)
"""

import os
import sys
import sqlite3
import subprocess
from pathlib import Path
from datetime import date, timedelta

# ── Config ────────────────────────────────────────────────────────────────────

REPO_DIR  = Path(__file__).parent
DB_PATH   = Path.home() / ".claude" / "usage.db"
TODAY     = date.today()
DATE_STR  = TODAY.isoformat()
NO_PUSH   = "--no-push" in sys.argv

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


# ── Step 1: Scan ──────────────────────────────────────────────────────────────

def run_scan():
    print("[1/4] Scanning usage logs...")
    sys.path.insert(0, str(REPO_DIR))
    from scanner import scan
    scan()
    print("      Done.")


# ── Step 2: Text report ───────────────────────────────────────────────────────

def build_text_report():
    print("[2/4] Building text report...")
    if not DB_PATH.exists():
        print("      No database found — nothing to report.")
        return None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    start_d  = TODAY - timedelta(days=6)
    start    = start_d.isoformat()

    # Today
    today_rows = conn.execute("""
        SELECT COALESCE(model,'unknown') as model,
               SUM(input_tokens) as inp, SUM(output_tokens) as out,
               SUM(cache_read_tokens) as cr, SUM(cache_creation_tokens) as cc,
               COUNT(*) as turns
        FROM turns WHERE substr(timestamp,1,10)=?
        GROUP BY model ORDER BY inp+out DESC
    """, (DATE_STR,)).fetchall()

    today_sessions = conn.execute("""
        SELECT COUNT(DISTINCT session_id) as cnt FROM turns
        WHERE substr(timestamp,1,10)=?
    """, (DATE_STR,)).fetchone()

    # Week by day
    week_by_day_model = conn.execute("""
        SELECT substr(timestamp,1,10) as day,
               COALESCE(model,'unknown') as model,
               SUM(input_tokens) as inp, SUM(output_tokens) as out,
               SUM(cache_read_tokens) as cr, SUM(cache_creation_tokens) as cc,
               COUNT(*) as turns
        FROM turns WHERE substr(timestamp,1,10) BETWEEN ? AND ?
        GROUP BY day, model
    """, (start, DATE_STR)).fetchall()

    week_by_model = conn.execute("""
        SELECT COALESCE(model,'unknown') as model,
               SUM(input_tokens) as inp, SUM(output_tokens) as out,
               SUM(cache_read_tokens) as cr, SUM(cache_creation_tokens) as cc,
               COUNT(*) as turns
        FROM turns WHERE substr(timestamp,1,10) BETWEEN ? AND ?
        GROUP BY model ORDER BY inp+out DESC
    """, (start, DATE_STR)).fetchall()

    week_sessions = conn.execute("""
        SELECT COUNT(DISTINCT session_id) as cnt FROM turns
        WHERE substr(timestamp,1,10) BETWEEN ? AND ?
    """, (start, DATE_STR)).fetchone()

    # All-time
    session_info = conn.execute("""
        SELECT COUNT(*) as sessions, MIN(first_timestamp) as first,
               MAX(last_timestamp) as last FROM sessions
    """).fetchone()

    totals = conn.execute("""
        SELECT SUM(input_tokens) as inp, SUM(output_tokens) as out,
               SUM(cache_read_tokens) as cr, SUM(cache_creation_tokens) as cc,
               COUNT(*) as turns FROM turns
    """).fetchone()

    by_model = conn.execute("""
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

    conn.close()

    lines = []
    w = lines.append
    SEP  = "-" * 60
    SEP2 = "=" * 60

    w(f"Claude Code Usage Report")
    w(f"Generated: {DATE_STR}")
    w(SEP2)

    # Today
    w(f"\nTODAY'S USAGE ({DATE_STR})")
    w(SEP)
    if not today_rows:
        w("  No usage recorded today.")
    else:
        t_inp = t_out = t_cr = t_cc = t_turns = 0
        t_cost = 0.0
        for r in today_rows:
            cost = calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
            t_cost += cost; t_inp += r["inp"] or 0; t_out += r["out"] or 0
            t_cr += r["cr"] or 0; t_cc += r["cc"] or 0; t_turns += r["turns"]
            w(f"  {r['model']:<30}  turns={r['turns']:<4}  in={fmt(r['inp'] or 0):<8}  out={fmt(r['out'] or 0):<8}  cost=${cost:.4f}")
        w(SEP)
        w(f"  {'TOTAL':<30}  turns={t_turns:<4}  in={fmt(t_inp):<8}  out={fmt(t_out):<8}  cost=${t_cost:.4f}")
        w(f"\n  Sessions today:   {today_sessions['cnt']}")
        w(f"  Cache read:       {fmt(t_cr)}")
        w(f"  Cache creation:   {fmt(t_cc)}")
    w(SEP)

    # Week
    per_day = {}
    for r in week_by_day_model:
        d = r["day"]
        b = per_day.setdefault(d, {"turns": 0, "inp": 0, "out": 0, "cost": 0.0})
        b["turns"] += r["turns"]; b["inp"] += r["inp"] or 0; b["out"] += r["out"] or 0
        b["cost"]  += calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)

    w(f"\nWEEKLY USAGE ({start} to {DATE_STR})")
    w(SEP)
    w("  By Day:")
    for i in range(7):
        d = (start_d + timedelta(days=i)).isoformat()
        b = per_day.get(d, {"turns": 0, "inp": 0, "out": 0, "cost": 0.0})
        w(f"    {d}  turns={b['turns']:<4}  in={fmt(b['inp']):<8}  out={fmt(b['out']):<8}  cost=${b['cost']:.4f}")
    w("  By Model:")
    wk_inp = wk_out = wk_cr = wk_cc = wk_turns = 0; wk_cost = 0.0
    for r in week_by_model:
        cost = calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
        wk_cost += cost; wk_inp += r["inp"] or 0; wk_out += r["out"] or 0
        wk_cr += r["cr"] or 0; wk_cc += r["cc"] or 0; wk_turns += r["turns"]
        w(f"    {r['model']:<30}  turns={r['turns']:<4}  in={fmt(r['inp'] or 0):<8}  out={fmt(r['out'] or 0):<8}  cost=${cost:.4f}")
    w(SEP)
    w(f"    {'TOTAL':<30}  turns={wk_turns:<4}  in={fmt(wk_inp):<8}  out={fmt(wk_out):<8}  cost=${wk_cost:.4f}")
    w(f"\n  Sessions this week:  {week_sessions['cnt']}")
    w(f"  Cache read:          {fmt(wk_cr)}")
    w(f"  Cache creation:      {fmt(wk_cc)}")
    w(SEP)

    # All-time
    total_cost = sum(calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0) for r in by_model)
    w(f"\nALL-TIME STATISTICS")
    w(SEP2)
    w(f"  Period:           {(session_info['first'] or '')[:10]} to {(session_info['last'] or '')[:10]}")
    w(f"  Total sessions:   {session_info['sessions'] or 0:,}")
    w(f"  Total turns:      {fmt(totals['turns'] or 0)}")
    w(f"\n  Input tokens:     {fmt(totals['inp'] or 0):<12}  (raw prompt tokens)")
    w(f"  Output tokens:    {fmt(totals['out'] or 0):<12}  (generated tokens)")
    w(f"  Cache read:       {fmt(totals['cr'] or 0):<12}  (90% cheaper than input)")
    w(f"  Cache creation:   {fmt(totals['cc'] or 0):<12}  (25% premium on input)")
    w(f"\n  Est. total cost:  ${total_cost:.4f}")
    w(SEP)
    w("  By Model:")
    for r in by_model:
        cost = calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
        w(f"    {r['model']:<30}  sessions={r['sessions']:<4}  turns={fmt(r['turns'] or 0):<6}  in={fmt(r['inp'] or 0):<8}  out={fmt(r['out'] or 0):<8}  cost=${cost:.4f}")
    w(SEP)
    w("  Top Projects:")
    for r in top_projects:
        w(f"    {(r['project_name'] or 'unknown'):<40}  sessions={r['sessions']:<3}  turns={fmt(r['turns'] or 0):<6}  tokens={fmt((r['inp'] or 0)+(r['out'] or 0))}")
    w(SEP2)

    text = "\n".join(lines) + "\n"
    out_path = REPO_DIR / f"Usage File for {DATE_STR}"
    out_path.write_text(text)
    print(f"      Saved: {out_path.name}")
    return out_path


# ── Step 3: Graphs ────────────────────────────────────────────────────────────

def build_graphs():
    print("[3/4] Generating graphs...")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np

    if not DB_PATH.exists():
        print("      No database — skipping graphs.")
        return None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    start_d = TODAY - timedelta(days=6)

    BLUE   = "#4A90D9"; GREEN  = "#5BAD6F"
    ORANGE = "#E8883A"; PURPLE = "#9B6BBE"
    GRAY   = "#AAAAAA"
    PALETTE = [BLUE, GREEN, ORANGE, PURPLE, "#D95B5B", GRAY]

    def fmtax(n): return f"{int(n/1000)}K" if n >= 1000 else str(int(n))

    fig, axes = plt.subplots(3, 2, figsize=(18, 20))
    fig.patch.set_facecolor("#1a1a2e")
    fig.suptitle(f"Claude API Usage Report — {DATE_STR}",
                 fontsize=22, fontweight="bold", color="white", y=0.99)

    def style(ax):
        ax.set_facecolor("#12122a")
        ax.tick_params(colors="white")
        ax.xaxis.label.set_color("white")
        ax.yaxis.label.set_color("white")
        ax.title.set_color("white")
        for spine in ax.spines.values():
            spine.set_edgecolor("#444466")
        ax.spines[["top","right"]].set_visible(False)
        ax.grid(axis="y", linestyle="--", alpha=0.3, color="#666688")

    # ── Chart 1: Token breakdown ──────────────────────────────────────────────
    ax = axes[0][0]
    row = conn.execute("""
        SELECT SUM(input_tokens) as inp, SUM(output_tokens) as out,
               SUM(cache_read_tokens) as cr, SUM(cache_creation_tokens) as cc
        FROM turns WHERE substr(timestamp,1,10)=?
    """, (DATE_STR,)).fetchone()
    vals   = [row["inp"] or 0, row["out"] or 0, row["cr"] or 0, row["cc"] or 0]
    labels = ["Input\nTokens", "Output\nTokens", "Cache\nRead", "Cache\nCreation"]
    bars = ax.bar(labels, vals, color=[BLUE, GREEN, ORANGE, PURPLE],
                  width=0.5, edgecolor="#1a1a2e", linewidth=1.2)
    for bar, v in zip(bars, vals):
        lbl = fmtax(v)
        ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+max(vals)*0.02,
                lbl, ha="center", va="bottom", fontsize=11, fontweight="bold", color="white")
    ax.set_title(f"Token Breakdown — {DATE_STR}", fontsize=13, fontweight="bold")
    ax.set_ylabel("Tokens", fontsize=11)
    ax.set_ylim(0, max(vals+[1])*1.2)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: fmtax(x)))
    style(ax)

    # ── Chart 2: Cost pie ─────────────────────────────────────────────────────
    ax = axes[0][1]
    inp_c = (row["inp"] or 0)*3.00/1e6
    out_c = (row["out"] or 0)*15.00/1e6
    cr_c  = (row["cr"]  or 0)*0.30/1e6
    cc_c  = (row["cc"]  or 0)*3.75/1e6
    total_c = inp_c+out_c+cr_c+cc_c
    pie_vals   = [inp_c, out_c, cr_c, cc_c]
    pie_labels = ["Input", "Output", "Cache Read", "Cache Creation"]
    wedges, _, autotexts = ax.pie(
        pie_vals, colors=[BLUE, GREEN, ORANGE, PURPLE],
        autopct=lambda p: f"{p:.1f}%" if p>0.5 else "",
        startangle=140, wedgeprops={"edgecolor":"#1a1a2e","linewidth":1.5})
    for at in autotexts:
        at.set_fontsize(10); at.set_fontweight("bold"); at.set_color("white")
    ax.legend([f"{l}  ${v:.4f}" for l,v in zip(pie_labels,pie_vals)],
              loc="lower center", bbox_to_anchor=(0.5,-0.1), ncol=2,
              fontsize=9, frameon=False, labelcolor="white")
    ax.set_title(f"Cost by Token Type — {DATE_STR}\nTotal: ${total_c:.4f}",
                 fontsize=13, fontweight="bold", color="white")
    ax.set_facecolor("#12122a")

    # ── Chart 3: Weekly turns ─────────────────────────────────────────────────
    ax = axes[1][0]
    rows = conn.execute("""
        SELECT substr(timestamp,1,10) as day, COUNT(*) as cnt FROM turns
        WHERE substr(timestamp,1,10) BETWEEN ? AND ?
        GROUP BY day
    """, (start_d.isoformat(), DATE_STR)).fetchall()
    day_counts = {r["day"]: r["cnt"] for r in rows}
    days   = [(start_d+timedelta(days=i)).isoformat() for i in range(7)]
    counts = [day_counts.get(d,0) for d in days]
    short  = [(start_d+timedelta(days=i)).strftime("%a\n%m/%d") for i in range(7)]
    bars = ax.bar(short, counts, color=[BLUE if c>0 else GRAY for c in counts],
                  width=0.55, edgecolor="#1a1a2e")
    for bar, v in zip(bars, counts):
        if v>0:
            ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.05,
                    str(v), ha="center", va="bottom", fontsize=11,
                    fontweight="bold", color="white")
    ax.set_title(f"Turns per Day — Last 7 Days", fontsize=13, fontweight="bold")
    ax.set_ylabel("Turns", fontsize=11)
    ax.set_ylim(0, max(counts+[1])*1.3)
    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    style(ax)

    # ── Chart 4: Turns by tool ────────────────────────────────────────────────
    ax = axes[1][1]
    rows = conn.execute("""
        SELECT COALESCE(tool_name,'unknown') as tool, COUNT(*) as cnt
        FROM turns WHERE substr(timestamp,1,10)=?
        GROUP BY tool ORDER BY cnt DESC
    """, (DATE_STR,)).fetchall()
    if rows:
        tools  = [r["tool"] for r in rows]
        tcnts  = [r["cnt"]  for r in rows]
        colors = [PALETTE[i%len(PALETTE)] for i in range(len(tools))]
        bars = ax.barh(tools[::-1], tcnts[::-1], color=colors[::-1],
                       height=0.5, edgecolor="#1a1a2e")
        for bar, v in zip(bars, tcnts[::-1]):
            ax.text(bar.get_width()+max(tcnts)*0.02, bar.get_y()+bar.get_height()/2,
                    str(v), va="center", fontsize=11, fontweight="bold", color="white")
        ax.set_xlim(0, max(tcnts)*1.25)
        ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))
        ax.grid(axis="x", linestyle="--", alpha=0.3, color="#666688")
        ax.grid(axis="y", visible=False)
    ax.set_title(f"Turns by Tool — {DATE_STR}", fontsize=13, fontweight="bold")
    ax.set_xlabel("Turns", fontsize=11)
    ax.set_facecolor("#12122a")
    ax.tick_params(colors="white")
    ax.xaxis.label.set_color("white")
    ax.title.set_color("white")
    for spine in ax.spines.values(): spine.set_edgecolor("#444466")
    ax.spines[["top","right"]].set_visible(False)

    # ── Chart 5: Tokens per turn ──────────────────────────────────────────────
    ax = axes[2][0]
    rows = conn.execute("""
        SELECT timestamp, input_tokens, output_tokens,
               cache_read_tokens, cache_creation_tokens, tool_name
        FROM turns WHERE substr(timestamp,1,10)=? ORDER BY timestamp
    """, (DATE_STR,)).fetchall()
    if rows:
        xs = np.arange(1, len(rows)+1)
        w2 = 0.2
        ax.bar(xs-1.5*w2, [r["input_tokens"] or 0 for r in rows],  w2, label="Input",          color=BLUE,   edgecolor="#1a1a2e")
        ax.bar(xs-0.5*w2, [r["output_tokens"] or 0 for r in rows], w2, label="Output",         color=GREEN,  edgecolor="#1a1a2e")
        ax.bar(xs+0.5*w2, [r["cache_read_tokens"] or 0 for r in rows], w2, label="Cache Read", color=ORANGE, edgecolor="#1a1a2e")
        ax.bar(xs+1.5*w2, [r["cache_creation_tokens"] or 0 for r in rows], w2, label="Cache Creation", color=PURPLE, edgecolor="#1a1a2e")
        ax.set_xticks(xs)
        ax.set_xticklabels([f"Turn {i}\n({r['tool_name'] or '?'})" for i,r in enumerate(rows,1)], fontsize=9)
        ax.legend(fontsize=9, frameon=False, labelcolor="white")
    ax.set_title(f"Tokens per Turn — {DATE_STR}", fontsize=13, fontweight="bold")
    ax.set_ylabel("Tokens", fontsize=11)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v,_: fmtax(v)))
    style(ax)

    # ── Chart 6: Cumulative cost (all-time by day) ────────────────────────────
    ax = axes[2][1]
    rows = conn.execute("""
        SELECT substr(timestamp,1,10) as day,
               COALESCE(model,'unknown') as model,
               SUM(input_tokens) as inp, SUM(output_tokens) as out,
               SUM(cache_read_tokens) as cr, SUM(cache_creation_tokens) as cc
        FROM turns GROUP BY day, model ORDER BY day
    """).fetchall()
    if rows:
        from collections import defaultdict
        day_cost = defaultdict(float)
        for r in rows:
            day_cost[r["day"]] += calc_cost(r["model"], r["inp"] or 0, r["out"] or 0, r["cr"] or 0, r["cc"] or 0)
        sorted_days = sorted(day_cost)
        costs = [day_cost[d] for d in sorted_days]
        cumulative = []
        running = 0.0
        for c in costs:
            running += c
            cumulative.append(running)
        ax.fill_between(range(len(sorted_days)), cumulative, alpha=0.3, color=BLUE)
        ax.plot(range(len(sorted_days)), cumulative, color=BLUE, linewidth=2.5, marker="o", markersize=5)
        step = max(1, len(sorted_days)//6)
        ax.set_xticks(range(0, len(sorted_days), step))
        ax.set_xticklabels([sorted_days[i] for i in range(0, len(sorted_days), step)],
                           rotation=30, ha="right", fontsize=8)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v,_: f"${v:.2f}"))
    ax.set_title("Cumulative Cost — All Time", fontsize=13, fontweight="bold")
    ax.set_ylabel("Cumulative Cost (USD)", fontsize=11)
    style(ax)

    conn.close()

    plt.tight_layout(rect=[0,0,1,0.97])
    out_path = REPO_DIR / f"Claude_Usage_Report_{DATE_STR}.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"      Saved: {out_path.name}")
    return out_path


# ── Step 4: Git commit & push ─────────────────────────────────────────────────

def git_push(files):
    if NO_PUSH:
        print("[4/4] Skipping git push (--no-push).")
        return
    print("[4/4] Committing and pushing to git...")
    names = [str(f.name) for f in files if f and f.exists()]
    if not names:
        print("      Nothing to commit.")
        return
    subprocess.run(["git", "-C", str(REPO_DIR), "add"] + names, check=True)
    msg = f"Daily usage report {DATE_STR}"
    subprocess.run(["git", "-C", str(REPO_DIR), "commit", "-m", msg], check=True)
    subprocess.run(["git", "-C", str(REPO_DIR), "push"], check=True)
    print("      Pushed.")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\nClaude Usage Daily Report — {DATE_STR}\n" + "="*45)
    run_scan()
    text_file  = build_text_report()
    graph_file = build_graphs()
    git_push([f for f in [text_file, graph_file] if f])
    print("\nDone.\n")
