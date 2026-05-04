import calendar as cal_mod
from datetime import date as date_type, datetime

from rich.panel import Panel
from rich.text import Text

from constants import LOCAL_TZ
from data import add_months
from constants import get_model_pricing
from utils import cost_for_tokens


def build_calendar_panel(all_sessions, month_offset=0):
    """Show a monthly calendar heatmap of daily usage.

    month_offset: 0 = current month, -1 = previous, etc.
    """
    now = datetime.now(LOCAL_TZ)
    year, month = add_months(now.year, now.month, month_offset)
    is_current_month = (month_offset == 0)

    daily_cost = {}
    for s in all_sessions:
        daily_by_model = s.get("daily_tokens_by_model", {})
        if daily_by_model:
            for day_str, models_dict in daily_by_model.items():
                d = date_type.fromisoformat(day_str)
                if d.year == year and d.month == month:
                    daily_cost[d] = daily_cost.get(d, 0) + sum(
                        cost_for_tokens(tok, get_model_pricing(model))
                        for model, tok in models_dict.items()
                    )
        else:
            pricing = get_model_pricing(s.get("last_prompt_model", "") or "")
            for day_str, tok in s.get("daily_tokens", {}).items():
                d = date_type.fromisoformat(day_str)
                if d.year == year and d.month == month:
                    daily_cost[d] = daily_cost.get(d, 0) + cost_for_tokens(tok, pricing)

    cal = cal_mod.monthcalendar(year, month)
    month_name = cal_mod.month_name[month]

    total_month_cost = sum(daily_cost.values())
    days_in_month = cal_mod.monthrange(year, month)[1]
    days_elapsed = now.day if is_current_month else days_in_month
    avg_daily = total_month_cost / days_elapsed if days_elapsed > 0 else 0
    projected = avg_daily * days_in_month

    lines = Text()
    lines.append(f"  {month_name} {year}", style="bold white")
    lines.append(f" — ", style="dim")
    if is_current_month:
        lines.append(f"${avg_daily:.2f}/day", style="bold yellow")
        lines.append(f"  ~${projected:.0f}/mo\n", style="dim yellow")
    else:
        lines.append(f"${total_month_cost:.0f} total", style="bold yellow")
        lines.append(f"  ${avg_daily:.2f}/day\n", style="dim yellow")
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
                elif cost >= 30:
                    style = "bold red"
                elif cost >= 20:
                    style = "rgb(255,165,0)"
                elif cost >= 10:
                    style = "bold yellow"
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
                    if cost >= 30:
                        style = "bold red"
                    elif cost >= 20:
                        style = "rgb(255,165,0)"
                    elif cost >= 10:
                        style = "bold yellow"
                    else:
                        style = "green"
                    cost_str = f"${cost:.0f}" if cost >= 10 else f"${cost:.1f}"
                    lines.append(f"{cost_str:^6}", style=style)
        lines.append("\n")

    # Legend
    lines.append("  ", style="dim")
    lines.append("██", style="green")
    lines.append("<$10 ", style="dim")
    lines.append("██", style="bold yellow")
    lines.append("<$20 ", style="dim")
    lines.append("██", style="rgb(255,165,0)")
    lines.append("<$30 ", style="dim")
    lines.append("██", style="bold red")
    lines.append("$30+\n", style="dim")
    lines.append("  ◀ ▶ browse months", style="dim")

    title = "Monthly Usage"
    if month_offset != 0:
        title = f"Monthly Usage  ({month_offset:+d}mo)"
    return Panel(lines, title=title, border_style="bright_cyan")
