from datetime import datetime

from rich.align import Align
from rich.panel import Panel
from rich.text import Text

from constants import LOCAL_TZ


def build_header():
    now = datetime.now(LOCAL_TZ)
    tz_name = now.strftime("%Z")
    return Panel(
        Align.center(
            Text(f"Claude Code Usage Monitor  |  {now.strftime('%Y-%m-%d %H:%M:%S')} {tz_name}", style="bold cyan")
        ),
        style="cyan",
        height=3,
    )
