"""Generate usage graphs from the Claude usage database."""

import sqlite3
from pathlib import Path
from datetime import date, timedelta
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

DB_PATH = Path.home() / ".claude" / "usage.db"
OUT_DIR = Path(__file__).parent
TODAY = date.today()

BLUE   = "#4A90D9"
GREEN  = "#5BAD6F"
ORANGE = "#E8883A"
PURPLE = "#9B6BBE"
RED    = "#D95B5B"
GRAY   = "#AAAAAA"

PALETTE = [BLUE, GREEN, ORANGE, PURPLE, RED, GRAY]

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fig_token_breakdown(conn):
    """Bar chart: token types for today."""
    today = TODAY.isoformat()
    row = conn.execute("""
        SELECT
            SUM(input_tokens)          as inp,
            SUM(output_tokens)         as out,
            SUM(cache_read_tokens)     as cr,
            SUM(cache_creation_tokens) as cc
        FROM turns
        WHERE substr(timestamp, 1, 10) = ?
    """, (today,)).fetchone()

    labels = ["Input\nTokens", "Output\nTokens", "Cache\nRead", "Cache\nCreation"]
    values = [row["inp"] or 0, row["out"] or 0, row["cr"] or 0, row["cc"] or 0]
    colors = [BLUE, GREEN, ORANGE, PURPLE]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(labels, values, color=colors, width=0.5, edgecolor="white", linewidth=1.2)

    for bar, val in zip(bars, values):
        label = f"{val:,}" if val < 1000 else f"{val/1000:.1f}K"
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(values) * 0.02,
                label, ha="center", va="bottom", fontsize=11, fontweight="bold")

    ax.set_title(f"Token Breakdown — {today}", fontsize=14, fontweight="bold", pad=14)
    ax.set_ylabel("Tokens", fontsize=11)
    ax.set_ylim(0, max(values) * 1.18)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{int(x/1000)}K" if x >= 1000 else str(int(x))))
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    fig.tight_layout()
    path = OUT_DIR / f"graph_token_breakdown_{today}.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {path.name}")
    return path


def fig_cost_by_token_type(conn):
    """Pie chart: cost share per token type."""
    PRICING = {
        "input":         3.00,
        "output":        15.00,
        "cache_read":    0.30,
        "cache_write":   3.75,
    }
    today = TODAY.isoformat()
    row = conn.execute("""
        SELECT
            SUM(input_tokens)          as inp,
            SUM(output_tokens)         as out,
            SUM(cache_read_tokens)     as cr,
            SUM(cache_creation_tokens) as cc
        FROM turns
        WHERE substr(timestamp, 1, 10) = ?
    """, (today,)).fetchone()

    costs = {
        "Input":          (row["inp"] or 0) * PRICING["input"]       / 1_000_000,
        "Output":         (row["out"] or 0) * PRICING["output"]      / 1_000_000,
        "Cache Read":     (row["cr"]  or 0) * PRICING["cache_read"]  / 1_000_000,
        "Cache Creation": (row["cc"]  or 0) * PRICING["cache_write"] / 1_000_000,
    }
    labels = list(costs.keys())
    values = list(costs.values())
    total = sum(values)

    fig, ax = plt.subplots(figsize=(7, 5))
    wedges, texts, autotexts = ax.pie(
        values,
        labels=None,
        colors=[BLUE, GREEN, ORANGE, PURPLE],
        autopct=lambda p: f"{p:.1f}%" if p > 0.5 else "",
        startangle=140,
        wedgeprops={"edgecolor": "white", "linewidth": 1.5},
    )
    for at in autotexts:
        at.set_fontsize(10)
        at.set_fontweight("bold")

    ax.legend(
        [f"{l}  ${v:.4f}" for l, v in zip(labels, values)],
        loc="lower center",
        bbox_to_anchor=(0.5, -0.12),
        ncol=2,
        fontsize=10,
        frameon=False,
    )
    ax.set_title(f"Cost Share by Token Type — {today}\nTotal: ${total:.4f}", fontsize=13, fontweight="bold", pad=14)
    fig.tight_layout()
    path = OUT_DIR / f"graph_cost_breakdown_{today}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {path.name}")
    return path


def fig_weekly_turns(conn):
    """Bar chart: turns per day for the last 7 days."""
    start_d = TODAY - timedelta(days=6)
    rows = conn.execute("""
        SELECT substr(timestamp, 1, 10) as day, COUNT(*) as cnt
        FROM turns
        WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?
        GROUP BY day
    """, (start_d.isoformat(), TODAY.isoformat())).fetchall()

    day_counts = {r["day"]: r["cnt"] for r in rows}
    days   = [(start_d + timedelta(days=i)).isoformat() for i in range(7)]
    counts = [day_counts.get(d, 0) for d in days]
    short  = [(start_d + timedelta(days=i)).strftime("%a\n%m/%d") for i in range(7)]

    fig, ax = plt.subplots(figsize=(9, 4.5))
    bars = ax.bar(short, counts, color=[BLUE if c > 0 else GRAY for c in counts],
                  width=0.55, edgecolor="white", linewidth=1.2)

    for bar, val in zip(bars, counts):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                    str(val), ha="center", va="bottom", fontsize=11, fontweight="bold")

    ax.set_title(f"Turns per Day — Last 7 Days ({start_d.isoformat()} to {TODAY.isoformat()})",
                 fontsize=13, fontweight="bold", pad=12)
    ax.set_ylabel("Turns", fontsize=11)
    ax.set_ylim(0, max(counts + [1]) * 1.3)
    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    fig.tight_layout()
    path = OUT_DIR / f"graph_weekly_turns_{TODAY.isoformat()}.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {path.name}")
    return path


def fig_turns_per_tool(conn):
    """Horizontal bar chart: turns broken down by tool used."""
    today = TODAY.isoformat()
    rows = conn.execute("""
        SELECT COALESCE(tool_name, 'unknown') as tool, COUNT(*) as cnt
        FROM turns
        WHERE substr(timestamp, 1, 10) = ?
        GROUP BY tool
        ORDER BY cnt DESC
    """, (today,)).fetchall()

    if not rows:
        return None

    tools  = [r["tool"] for r in rows]
    counts = [r["cnt"]  for r in rows]
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(tools))]

    fig, ax = plt.subplots(figsize=(8, max(3, len(tools) * 0.7 + 1.5)))
    bars = ax.barh(tools[::-1], counts[::-1], color=colors[::-1],
                   height=0.5, edgecolor="white", linewidth=1.2)

    for bar, val in zip(bars, counts[::-1]):
        ax.text(bar.get_width() + max(counts) * 0.02, bar.get_y() + bar.get_height() / 2,
                str(val), va="center", fontsize=11, fontweight="bold")

    ax.set_title(f"Turns by Tool — {today}", fontsize=13, fontweight="bold", pad=12)
    ax.set_xlabel("Turns", fontsize=11)
    ax.set_xlim(0, max(counts) * 1.25)
    ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", linestyle="--", alpha=0.4)
    fig.tight_layout()
    path = OUT_DIR / f"graph_turns_by_tool_{today}.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {path.name}")
    return path


def fig_tokens_per_turn(conn):
    """Line/scatter: input + output tokens across each turn (chronological)."""
    today = TODAY.isoformat()
    rows = conn.execute("""
        SELECT timestamp, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, tool_name
        FROM turns
        WHERE substr(timestamp, 1, 10) = ?
        ORDER BY timestamp
    """, (today,)).fetchall()

    if not rows:
        return None

    x      = list(range(1, len(rows) + 1))
    inp    = [r["input_tokens"] or 0 for r in rows]
    out    = [r["output_tokens"] or 0 for r in rows]
    cr     = [r["cache_read_tokens"] or 0 for r in rows]
    cc     = [r["cache_creation_tokens"] or 0 for r in rows]
    tools  = [r["tool_name"] or "?" for r in rows]

    fig, ax = plt.subplots(figsize=(9, 5))
    width = 0.2
    xs = np.array(x)

    ax.bar(xs - 1.5*width, inp, width, label="Input",          color=BLUE,   edgecolor="white")
    ax.bar(xs - 0.5*width, out, width, label="Output",         color=GREEN,  edgecolor="white")
    ax.bar(xs + 0.5*width, cr,  width, label="Cache Read",     color=ORANGE, edgecolor="white")
    ax.bar(xs + 1.5*width, cc,  width, label="Cache Creation", color=PURPLE, edgecolor="white")

    ax.set_xticks(xs)
    ax.set_xticklabels([f"Turn {i}\n({t})" for i, t in zip(x, tools)], fontsize=9)
    ax.set_title(f"Tokens per Turn — {today}", fontsize=13, fontweight="bold", pad=12)
    ax.set_ylabel("Tokens", fontsize=11)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v/1000)}K" if v >= 1000 else str(int(v))))
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.legend(fontsize=10, frameon=False)
    fig.tight_layout()
    path = OUT_DIR / f"graph_tokens_per_turn_{today}.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {path.name}")
    return path


if __name__ == "__main__":
    print(f"Generating graphs for {TODAY.isoformat()}...")
    conn = connect()
    fig_token_breakdown(conn)
    fig_cost_by_token_type(conn)
    fig_weekly_turns(conn)
    fig_turns_per_tool(conn)
    fig_tokens_per_turn(conn)
    conn.close()
    print("Done.")
