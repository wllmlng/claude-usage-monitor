from datetime import datetime, timezone, timedelta

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from constants import LOCAL_TZ
from data import calc_burn_rate, aggregate_hourly, estimate_cost_for_dates
from utils import estimate_cost, format_tokens, format_cost


def build_burn_panel(today_sessions):
    rate = calc_burn_rate(today_sessions)
    today = datetime.now(LOCAL_TZ).date()
    today_cost = estimate_cost_for_dates(today_sessions, today, today)
    now = datetime.now(LOCAL_TZ)
    hours_today = max((now - datetime.combine(today, datetime.min.time(), tzinfo=LOCAL_TZ)).total_seconds() / 3600, 0.1)
    cost_per_hr = today_cost / hours_today

    total_msgs = sum(s.get("user_message_count", 0) for s in today_sessions)
    total_tools = sum(s.get("tool_calls", 0) for s in today_sessions)

    ten_min_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
    active = [
        s for s in today_sessions
        if datetime.fromisoformat(s["last_activity"]) >= ten_min_ago
    ]

    # Hourly usage chart
    hourly = aggregate_hourly(today_sessions)
    current_hour = datetime.now(LOCAL_TZ).hour
    start_hour = 6
    end_hour = current_hour + 1
    visible_hours = hourly[start_hour:end_hour] if end_hour > start_hour else hourly[start_hour:]

    # Left column: stats
    left = Text()
    left.append(f"Burn Rate:      ", style="bold white")
    left.append(f"{format_tokens(int(rate))}/hr\n", style="bold white")
    left.append(f"                ", style="bold white")
    left.append(f"{format_cost(cost_per_hr)}/hr\n\n", style="bold yellow")
    left.append(f"Sessions Today: {len(today_sessions)}\n", style="bold white")
    if active:
        left.append(f"Active Now:     {len(active)}\n", style="bold green")
    else:
        left.append(f"Active Now:     0\n", style="dim")
    left.append(f"Messages:       {total_msgs}\n", style="bold white")
    left.append(f"Tool Calls:     {total_tools}\n", style="bold white")

    # Right column: vertical hourly bar chart
    right = Text()
    right.append("Hourly Usage:\n", style="bold white")
    max_val = max(visible_hours) if visible_hours and max(visible_hours) > 0 else 1
    chart_height = 7
    for row in range(chart_height, 0, -1):
        threshold = max_val * row / chart_height
        if row > 5:
            bar_style = "bold red"
        elif row > 3:
            bar_style = "rgb(255,165,0)"
        else:
            bar_style = "bright_yellow"
        right.append(" ", style="dim")
        for val in visible_hours:
            if val >= threshold and val > 0:
                right.append("██", style=bar_style)
            else:
                right.append("  ", style="dim")
            right.append("  ", style="dim")
        right.append("\n")
    right.append(" ", style="dim")
    for i in range(len(visible_hours)):
        h = start_hour + i
        display_h = h if h <= 12 else h - 12
        suffix = "a" if h < 12 else "p"
        label = f"{display_h}{suffix}"
        right.append(f"{label:<4}", style="dim")
    right.append("\n Peak: ", style="dim")
    right.append(f"{format_tokens(max_val)}", style="bold white")

    grid = Table.grid(padding=(0, 1))
    grid.add_column(width=30)
    grid.add_column(ratio=1)
    grid.add_row(left, right)

    return Panel(grid, title="Burn Rate & Activity", border_style="yellow")
