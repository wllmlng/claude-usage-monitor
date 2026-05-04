from datetime import datetime

from rich.panel import Panel
from rich.table import Table

from constants import LOCAL_TZ
from data import aggregate_tokens_for_dates, estimate_cost_for_dates
from utils import estimate_cost, format_tokens, format_cost


def build_projects_panel(today_sessions, all_sessions, view_date=None, is_current=True):
    today = view_date or datetime.now(LOCAL_TZ).date()
    day_label = "Today" if is_current else today.strftime("%b %-d")
    today_by_project = {}
    for s in today_sessions:
        name = s.get("project_name", "unknown")
        if name not in today_by_project:
            today_by_project[name] = []
        today_by_project[name].append(s)

    all_by_project = {}
    for s in all_sessions:
        name = s.get("project_name", "unknown")
        if name in today_by_project:
            if name not in all_by_project:
                all_by_project[name] = []
            all_by_project[name].append(s)

    table = Table(expand=True)
    table.add_column("Project", style="cyan")
    table.add_column(f"{day_label} Tokens", justify="right", style="bold")
    table.add_column(f"{day_label} Cost", justify="right", style="yellow")
    table.add_column("All Time Tokens", justify="right", style="dim bold")
    table.add_column("All Time Cost", justify="right", style="dim yellow")
    table.add_column("Models", style="dim")

    today_totals = {
        name: sum(aggregate_tokens_for_dates(sessions, today, today))
        for name, sessions in today_by_project.items()
    }

    for name in sorted(today_by_project.keys(), key=lambda n: -today_totals[n]):
        today_s = today_by_project[name]
        all_s = all_by_project.get(name, [])

        today_tok = today_totals[name]
        all_tok = sum(
            s.get("input_tokens", 0) + s.get("output_tokens", 0)
            + s.get("cache_read_tokens", 0) + s.get("cache_create_tokens", 0)
            for s in all_s
        )

        today_cost = estimate_cost_for_dates(today_s, today, today)
        all_cost = estimate_cost(all_s)

        project_models = set()
        for s in today_s:
            project_models.update(s.get("models", []))
        short_models = []
        for m in sorted(project_models):
            parts = m.replace("claude-", "").split("-")
            if len(parts) >= 3:
                short_models.append(f"{parts[0]} {parts[1]}.{parts[2]}")
            else:
                short_models.append(m)
        model_str = ", ".join(short_models)

        table.add_row(
            name,
            format_tokens(today_tok),
            format_cost(today_cost),
            format_tokens(all_tok),
            format_cost(all_cost),
            model_str,
        )

    if not today_by_project:
        table.add_row(f"[dim]No sessions on {day_label}[/]", "", "", "", "", "")

    return Panel(table, title=f"Project Breakdown ({day_label} + All Time)", border_style="blue")
