import calendar as cal_mod
from datetime import date as date_type, datetime

from rich.panel import Panel
from rich.text import Text

from constants import LOCAL_TZ, MODEL_PRICING


def build_calendar_panel(all_sessions):
    """Show a monthly calendar heatmap of daily usage."""
    now = datetime.now(LOCAL_TZ)
    year, month = now.year, now.month

    # Aggregate per-day token costs from actual timestamps
    daily_cost = {}
    for s in all_sessions:
        models = s.get("models", [])
        model_str = " ".join(models).lower()
        if "opus" in model_str:
            pricing = MODEL_PRICING["opus"]
        elif "haiku" in model_str:
            pricing = MODEL_PRICING["haiku"]
        else:
            pricing = MODEL_PRICING["sonnet"]

        for day_str, tok in s.get("daily_tokens", {}).items():
            d = date_type.fromisoformat(day_str)
            if d.year == year and d.month == month:
                cost = (
                    tok["input"] / 1_000_000 * pricing["input"]
                    + tok["output"] / 1_000_000 * pricing["output"]
                    + tok["cache_read"] / 1_000_000 * pricing["cache_read"]
                    + tok["cache_create"] / 1_000_000 * pricing["cache_create"]
                )
                daily_cost[d] = daily_cost.get(d, 0) + cost

    max_cost = max(daily_cost.values()) if daily_cost else 1.0

    cal = cal_mod.monthcalendar(year, month)
    month_name = cal_mod.month_name[month]

    # Compute avg/projected early for header
    import calendar as cal_stdlib
    total_month_cost = sum(daily_cost.values())
    days_elapsed = now.day
    days_in_month = cal_stdlib.monthrange(year, month)[1]
    avg_daily = total_month_cost / days_elapsed if days_elapsed > 0 else 0
    projected = avg_daily * days_in_month

    lines = Text()
    lines.append(f"  {month_name} {year}", style="bold white")
    lines.append(f" — ", style="dim")
    lines.append(f"${avg_daily:.2f}/day", style="bold yellow")
    lines.append(f"  ~${projected:.0f}/mo\n", style="dim yellow")
    lines.append("  Mon   Tue   Wed   Thu   Fri   Sat   Sun\n", style="dim")

    for week in cal:
        # Day number row
        lines.append(" ", style="dim")
        for day in week:
            if day == 0:
                lines.append("      ", style="dim")
            else:
                d = date_type(year, month, day)
                cost = daily_cost.get(d, 0)
                if cost == 0:
                    style = "dim"
                else:
                    ratio = cost / max_cost if max_cost > 0 else 0
                    if ratio > 0.75:
                        style = "bold red"
                    elif ratio > 0.5:
                        style = "bold yellow"
                    elif ratio > 0.25:
                        style = "bold green"
                    else:
                        style = "green"
                lines.append(f"  {day:>2}  ", style=style)
        lines.append("\n")
        # Cost row
        lines.append(" ", style="dim")
        for day in week:
            if day == 0:
                lines.append("      ", style="dim")
            else:
                d = date_type(year, month, day)
                cost = daily_cost.get(d, 0)
                if cost == 0:
                    lines.append("   ·  ", style="dim")
                else:
                    ratio = cost / max_cost if max_cost > 0 else 0
                    if ratio > 0.75:
                        style = "bold red"
                    elif ratio > 0.5:
                        style = "bold yellow"
                    elif ratio > 0.25:
                        style = "bold green"
                    else:
                        style = "green"
                    cost_str = f"${cost:.0f}" if cost >= 10 else f"${cost:.1f}"
                    lines.append(f"{cost_str:^6}", style=style)
        lines.append("\n")

    # Legend
    lines.append("  ", style="dim")
    lines.append("██", style="green")
    lines.append("<$10 ", style="dim")
    lines.append("██", style="bold green")
    lines.append("<$25 ", style="dim")
    lines.append("██", style="bold yellow")
    lines.append("<$50 ", style="dim")
    lines.append("██", style="bold red")
    lines.append("$50+", style="dim")

    return Panel(lines, title="Monthly Usage", border_style="bright_cyan")
