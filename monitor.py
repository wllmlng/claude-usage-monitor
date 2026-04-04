#!/usr/bin/env python3
"""Live terminal dashboard for Claude Code token usage."""

from time import sleep

from rich.console import Console
from rich.layout import Layout
from rich.live import Live

from data import scan_live_sessions, filter_today
from panels import (
    build_header,
    build_token_panel,
    build_burn_panel,
    build_projects_panel,
    build_recent_panel,
    build_calendar_panel,
    build_last_prompt_panel,
)


def build_dashboard():
    all_sessions = scan_live_sessions()
    today_sessions = filter_today(all_sessions)

    layout = Layout()
    layout.split_column(
        Layout(build_header(), name="header", size=3),
        Layout(name="top"),
        Layout(name="middle"),
        Layout(name="bottom", size=min(len(set(s["project_name"] for s in today_sessions)) + 5, 12)),
    )
    layout["top"].split_row(
        Layout(build_token_panel(all_sessions), name="tokens"),
        Layout(build_burn_panel(today_sessions), name="burn"),
    )
    layout["middle"].split_row(
        Layout(build_projects_panel(today_sessions, all_sessions), name="projects"),
        Layout(build_recent_panel(all_sessions), name="recent"),
        Layout(build_calendar_panel(all_sessions), name="calendar"),
    )
    layout["bottom"].update(build_last_prompt_panel(today_sessions))
    return layout


def main():
    console = Console()
    console.clear()

    try:
        with Live(build_dashboard(), console=console, refresh_per_second=0.5, screen=True) as live:
            while True:
                sleep(1)
                live.update(build_dashboard())
    except KeyboardInterrupt:
        console.print("\n[dim]Monitor stopped.[/]")


if __name__ == "__main__":
    main()
