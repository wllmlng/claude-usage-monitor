#!/usr/bin/env python3
"""Live terminal dashboard for Claude Code token usage."""

import os
import select
import sys
import termios
import tty
from datetime import datetime
from time import sleep

from rich.console import Console
from rich.layout import Layout
from rich.live import Live

from constants import LOCAL_TZ
from data import add_months, scan_live_sessions, filter_for_date, resolve_view_date
from panels import (
    build_header,
    build_token_panel,
    build_burn_panel,
    build_projects_panel,
    build_recent_panel,
    build_calendar_panel,
    build_last_prompt_panel,
)


def build_dashboard(month_offset=0):
    all_sessions = scan_live_sessions()

    now = datetime.now(LOCAL_TZ)
    view_year, view_month = add_months(now.year, now.month, month_offset)
    is_current = (month_offset == 0)
    view_date = resolve_view_date(all_sessions, view_year, view_month)

    view_sessions = filter_for_date(all_sessions, view_date)

    layout = Layout()
    layout.split_column(
        Layout(build_header(view_date, is_current), name="header", size=3),
        Layout(name="top"),
        Layout(name="middle", size=12),
        Layout(name="bottom", size=min(len(set(s["project_name"] for s in view_sessions)) + 5, 12)),
    )
    layout["top"].split_row(
        Layout(build_token_panel(all_sessions, view_date, is_current), name="tokens", ratio=3),
        Layout(build_burn_panel(view_sessions, view_date, is_current), name="burn", ratio=4),
        Layout(build_calendar_panel(all_sessions, month_offset), name="calendar", ratio=2),
    )
    layout["middle"].split_row(
        Layout(build_projects_panel(view_sessions, all_sessions, view_date, is_current), name="projects"),
        Layout(build_recent_panel(all_sessions, view_date, is_current), name="recent"),
    )
    layout["bottom"].update(build_last_prompt_panel(view_sessions, view_date, is_current))
    return layout


def read_key(fd):
    """Non-blocking read of the most recent arrow-key press. Returns 'left', 'right', or None."""
    if not select.select([fd], [], [], 0)[0]:
        return None
    try:
        data = os.read(fd, 32)
    except (BlockingIOError, OSError):
        return None
    if not data:
        return None
    # An arrow press is 3 bytes: ESC [ D/C/A/B. Held keys deliver multiple
    # sequences in one read; we only care about the most recent.
    last = None
    i = 0
    while i < len(data):
        if data[i] == 0x1b and i + 2 < len(data) and data[i + 1] == ord("["):
            code = data[i + 2]
            if code == ord("D"):
                last = "left"
            elif code == ord("C"):
                last = "right"
            i += 3
        else:
            i += 1
    return last


def main():
    console = Console()
    console.clear()

    month_offset = 0
    stdin_fd = sys.stdin.fileno()
    old_settings = None
    try:
        if sys.stdin.isatty():
            old_settings = termios.tcgetattr(stdin_fd)
            tty.setcbreak(stdin_fd)

        # Poll stdin every POLL_S; rebuild the dashboard on key press or every REFRESH_TICKS polls.
        POLL_S = 0.05
        REFRESH_TICKS = 20  # 1 Hz at 50ms poll
        with Live(build_dashboard(month_offset), console=console, refresh_per_second=10, screen=True) as live:
            tick = 0
            while True:
                sleep(POLL_S)
                key = read_key(stdin_fd) if old_settings is not None else None
                if key == "left":
                    month_offset -= 1
                elif key == "right" and month_offset < 0:
                    month_offset += 1

                tick += 1
                if key or tick >= REFRESH_TICKS:
                    live.update(build_dashboard(month_offset))
                    tick = 0
    except KeyboardInterrupt:
        console.print("\n[dim]Monitor stopped.[/]")
    finally:
        if old_settings is not None:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_settings)


if __name__ == "__main__":
    main()
