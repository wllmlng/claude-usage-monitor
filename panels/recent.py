from datetime import datetime, timezone, timedelta

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from constants import LOCAL_TZ
from utils import estimate_cost, format_tokens, format_cost


def build_recent_panel(sessions, view_date=None, is_current=True):
    if not is_current and view_date is not None:
        filtered = []
        for s in sessions:
            last = datetime.fromisoformat(s["last_activity"]).astimezone(LOCAL_TZ).date()
            if last.year == view_date.year and last.month == view_date.month:
                filtered.append(s)
        sessions = filtered
    sorted_sessions = sorted(sessions, key=lambda s: s.get("last_activity", ""), reverse=True)[:6]

    table = Table(expand=True)
    table.add_column("Last Active", style="dim")
    table.add_column("Project", style="cyan")
    table.add_column("Duration", justify="right")
    table.add_column("Msgs", justify="right")
    table.add_column("Tokens", justify="right", style="bold")
    table.add_column("Cost", justify="right", style="yellow")

    ten_min_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
    for s in sorted_sessions:
        last_utc = datetime.fromisoformat(s["last_activity"])
        last = last_utc.astimezone(LOCAL_TZ)
        dur = s.get("duration_minutes", 0)
        hours = dur // 60
        mins = dur % 60
        dur_str = f"{hours}h {mins}m" if hours > 0 else f"{mins}m"
        total = (
            s.get("input_tokens", 0) + s.get("output_tokens", 0)
            + s.get("cache_read_tokens", 0) + s.get("cache_create_tokens", 0)
        )
        msgs = s.get("user_message_count", 0)
        cost = estimate_cost([s])

        style = "bold green" if (is_current and last_utc >= ten_min_ago) else ""

        table.add_row(
            Text(last.strftime("%m/%d %I:%M%p"), style=style),
            Text(s.get("project_name", "?"), style=style or "cyan"),
            dur_str,
            str(msgs),
            format_tokens(total),
            format_cost(cost),
        )

    return Panel(table, title="Recent Sessions", border_style="magenta")
