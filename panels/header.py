from datetime import datetime

from rich.align import Align
from rich.panel import Panel
from rich.text import Text

from constants import LOCAL_TZ


def build_header(view_date=None, is_current=True):
    now = datetime.now(LOCAL_TZ)
    tz_name = now.strftime("%Z")
    if is_current or view_date is None:
        text = Text(f"Claude Code Usage Monitor  |  {now.strftime('%Y-%m-%d %H:%M:%S')} {tz_name}", style="bold cyan")
        style = "cyan"
    else:
        text = Text()
        text.append("Claude Code Usage Monitor  |  ", style="bold cyan")
        text.append(f"Viewing {view_date.strftime('%B %Y')}", style="bold yellow")
        text.append(f"  |  ◀ ▶ navigate · → return to current", style="dim")
        style = "yellow"
    return Panel(Align.center(text), style=style, height=3)
