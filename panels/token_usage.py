from datetime import datetime, timedelta

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from constants import LOCAL_TZ
from data import aggregate_tokens_for_dates, estimate_cost_for_dates
from utils import horizontal_bar, format_tokens, format_cost


def build_token_panel(all_sessions):
    today = datetime.now(LOCAL_TZ).date()
    monday = (today - timedelta(days=today.weekday()))
    sunday = monday + timedelta(days=6)

    today_in, today_out, today_cr, today_cc = aggregate_tokens_for_dates(all_sessions, today, today)
    today_total = today_in + today_out + today_cr + today_cc

    week_in, week_out, week_cr, week_cc = aggregate_tokens_for_dates(all_sessions, monday, sunday)
    week_total = week_in + week_out + week_cr + week_cc

    today_cost = estimate_cost_for_dates(all_sessions, today, today)
    week_cost = estimate_cost_for_dates(all_sessions, monday, sunday)
    month_start = today.replace(day=1)
    month_cost = estimate_cost_for_dates(all_sessions, month_start, today)
    m_in, m_out, m_cr, m_cc = aggregate_tokens_for_dates(all_sessions, month_start, today)
    month_total = m_in + m_out + m_cr + m_cc

    today_key = today.isoformat()
    today_msgs = sum(s.get("daily_messages", {}).get(today_key, 0) for s in all_sessions)
    avg_cost = today_cost / today_msgs if today_msgs > 0 else 0

    # Token type breakdown bar — based on most recently active session
    active_session = max(
        (s for s in all_sessions if s.get("daily_tokens", {}).get(today.isoformat())),
        key=lambda s: s["last_activity"],
        default=None,
    )
    if active_session:
        active_name = active_session.get("project_name", "unknown")
        at = active_session.get("daily_tokens", {}).get(today.isoformat(), {})
        a_in, a_out = at.get("input", 0), at.get("output", 0)
        a_cr, a_cc = at.get("cache_read", 0), at.get("cache_create", 0)
    else:
        active_name = "—"
        a_in, a_out, a_cr, a_cc = today_in, today_out, today_cr, today_cc
    breakdown = horizontal_bar([
        (a_in, "bright_blue", "input"),
        (a_out, "bright_green", "output"),
        (a_cr, "bright_cyan", "cache read"),
        (a_cc, "bright_magenta", "cache create"),
    ], width=36)

    # Left column: totals
    left = Text()
    left.append("Today ", style="bold white")
    left.append(f"{format_tokens(today_total)} ", style="bold white")
    left.append(f"{format_cost(today_cost)}\n", style="bold yellow")
    left.append("Week  ", style="bold white")
    left.append(f"{format_tokens(week_total)} ", style="bold white")
    left.append(f"{format_cost(week_cost)}\n", style="bold yellow")
    left.append("Month ", style="bold white")
    left.append(f"{format_tokens(month_total)} ", style="bold white")
    left.append(f"{format_cost(month_cost)}\n\n", style="bold yellow")
    left.append("Avg Cost/Prompt (today) ", style="dim")
    left.append(f"{format_cost(avg_cost)}\n", style="bold yellow")

    # Right column: breakdown bar
    right = Text()
    right.append(f"Active ({active_name}):\n", style="bold white")
    right.append("  ")
    right.append_text(breakdown)
    right.append("\n  ")
    right.append("██", style="bright_blue")
    right.append(" in ", style="dim")
    right.append("██", style="bright_green")
    right.append(" out\n  ", style="dim")
    right.append("██", style="bright_cyan")
    right.append(f" c/r({format_tokens(a_cr)}) ", style="dim")
    right.append("██", style="bright_magenta")
    right.append(f" c/w({format_tokens(a_cc)})\n", style="dim")

    grid = Table.grid(padding=(0, 2))
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)
    grid.add_row(left, right)

    return Panel(grid, title="Token Usage", border_style="green")
