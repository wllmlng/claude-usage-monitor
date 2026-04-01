#!/usr/bin/env python3
"""Live terminal dashboard for Claude Code token usage."""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from time import sleep
from zoneinfo import ZoneInfo

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text
from rich.align import Align

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
SESSION_META_DIR = CLAUDE_DIR / "usage-data" / "session-meta"
LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# Rough estimate for the 5-hour rolling window.
# Anthropic doesn't publish exact token limits — this is a best guess
# based on community reports for Max 5x ($100/mo). Adjust as needed.
# Pro (~45 prompts/5h), Max 5x (~225 prompts/5h), Max 20x (~900 prompts/5h)
ESTIMATED_5H_TOKEN_LIMIT = 5_000_000

# API pricing per million tokens (for "what would this cost" estimates)
# Source: https://platform.claude.com/docs/en/about-claude/pricing
#
# Model          | Input  | Output | Cache Read | Cache Create
# -------------- | ------ | ------ | ---------- | ------------
# Opus 4.6       | $5.00  | $25.00 | $0.50      | $6.25
# Sonnet 4.6     | $3.00  | $15.00 | $0.30      | $3.75
# Haiku 4.5      | $1.00  | $5.00  | $0.10      | $1.25
MODEL_PRICING = {
    "opus": {"input": 5.0, "output": 25.0, "cache_read": 0.50, "cache_create": 6.25},
    "sonnet": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_create": 3.75},
    "haiku": {"input": 1.0, "output": 5.0, "cache_read": 0.10, "cache_create": 1.25},
}


def estimate_cost(sessions):
    """Estimate what the usage would cost on API pricing."""
    total_cost = 0.0
    for s in sessions:
        # Determine pricing tier from model names
        models = s.get("models", [])
        model_str = " ".join(models).lower()
        if "opus" in model_str:
            pricing = MODEL_PRICING["opus"]
        elif "haiku" in model_str:
            pricing = MODEL_PRICING["haiku"]
        else:
            pricing = MODEL_PRICING["sonnet"]

        total_cost += s.get("input_tokens", 0) / 1_000_000 * pricing["input"]
        total_cost += s.get("output_tokens", 0) / 1_000_000 * pricing["output"]
        total_cost += s.get("cache_read_tokens", 0) / 1_000_000 * pricing["cache_read"]
        total_cost += s.get("cache_create_tokens", 0) / 1_000_000 * pricing["cache_create"]
    return total_cost


def format_cost(cost):
    """Format cost as dollars."""
    if cost >= 1.0:
        return f"${cost:.2f}"
    return f"${cost:.3f}"


# Cache: path -> (mtime, file_size, parsed_session)
_session_cache: dict[str, tuple[float, int, dict]] = {}


def scan_live_sessions():
    """Scan JSONL conversation logs with caching.

    Only re-parses files whose mtime or size changed since last check.
    """
    global _session_cache
    sessions = []
    if not PROJECTS_DIR.exists():
        return sessions

    seen_paths = set()

    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl_path in project_dir.glob("*.jsonl"):
            path_key = str(jsonl_path)
            seen_paths.add(path_key)

            try:
                stat = jsonl_path.stat()
                mtime = stat.st_mtime
                size = stat.st_size
            except OSError:
                continue

            # Check cache — skip re-parse if file hasn't changed
            cached = _session_cache.get(path_key)
            if cached and cached[0] == mtime and cached[1] == size:
                sessions.append(cached[2])
                continue

            # File changed or new — parse it
            session = parse_jsonl_session(jsonl_path, project_dir.name)
            if session:
                _session_cache[path_key] = (mtime, size, session)
                sessions.append(session)

    # Clean up deleted files from cache
    for key in list(_session_cache.keys()):
        if key not in seen_paths:
            del _session_cache[key]

    return sessions


def parse_jsonl_session(path, project_dir_name):
    """Parse a JSONL conversation log and extract token usage."""
    input_tokens = 0
    output_tokens = 0
    cache_read = 0
    cache_create = 0
    user_messages = 0
    assistant_messages = 0
    tool_calls = 0
    models_used = set()
    first_ts = None
    last_ts = None
    session_id = path.stem

    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts_str = entry.get("timestamp")
                if ts_str:
                    ts = datetime.fromisoformat(ts_str)
                    if first_ts is None or ts < first_ts:
                        first_ts = ts
                    if last_ts is None or ts > last_ts:
                        last_ts = ts

                msg = entry.get("message", {})
                role = msg.get("role")
                usage = msg.get("usage", {})

                if role == "user" and entry.get("type") == "user":
                    content = msg.get("content")
                    if isinstance(content, str):
                        user_messages += 1

                if role == "assistant":
                    assistant_messages += 1
                    model = msg.get("model", "")
                    if model:
                        models_used.add(model)

                    input_tokens += usage.get("input_tokens", 0)
                    output_tokens += usage.get("output_tokens", 0)
                    cache_read += usage.get("cache_read_input_tokens", 0)
                    cache_create += usage.get("cache_creation_input_tokens", 0)

                    for block in msg.get("content", []):
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_calls += 1

    except OSError:
        return None

    if first_ts is None:
        return None

    project_name = project_dir_name.split("-")[-1] if "-" in project_dir_name else project_dir_name

    duration_minutes = 0
    if first_ts and last_ts:
        duration_minutes = int((last_ts - first_ts).total_seconds() / 60)

    return {
        "session_id": session_id,
        "project_name": project_name,
        "start_time": first_ts.isoformat(),
        "last_activity": last_ts.isoformat(),
        "duration_minutes": duration_minutes,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read,
        "cache_create_tokens": cache_create,
        "user_message_count": user_messages,
        "assistant_message_count": assistant_messages,
        "tool_calls": tool_calls,
        "models": list(models_used),
    }


def filter_today(sessions):
    """Filter sessions that have activity today (Pacific time)."""
    today = datetime.now(LOCAL_TZ).date()
    return [
        s for s in sessions
        if datetime.fromisoformat(s["last_activity"]).astimezone(LOCAL_TZ).date() == today
        or datetime.fromisoformat(s["start_time"]).astimezone(LOCAL_TZ).date() == today
    ]


def filter_rolling_5h(sessions):
    """Filter sessions with activity in the last 5 hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=5)
    return [
        s for s in sessions
        if datetime.fromisoformat(s["last_activity"]) >= cutoff
    ]


def aggregate_tokens(sessions):
    """Sum tokens across sessions."""
    total_input = sum(s.get("input_tokens", 0) for s in sessions)
    total_output = sum(s.get("output_tokens", 0) for s in sessions)
    total_cache_read = sum(s.get("cache_read_tokens", 0) for s in sessions)
    total_cache_create = sum(s.get("cache_create_tokens", 0) for s in sessions)
    return total_input, total_output, total_cache_read, total_cache_create


def calc_burn_rate(sessions):
    """Tokens per hour based on session activity window."""
    if not sessions:
        return 0.0
    timestamps = []
    for s in sessions:
        timestamps.append(datetime.fromisoformat(s["start_time"]))
        timestamps.append(datetime.fromisoformat(s["last_activity"]))
    earliest = min(timestamps)
    now = datetime.now(timezone.utc)
    hours = max((now - earliest).total_seconds() / 3600, 0.1)
    inp, out, cache_r, cache_c = aggregate_tokens(sessions)
    return (inp + out + cache_r + cache_c) / hours


def format_tokens(n):
    """Human-readable token count."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def build_header():
    now = datetime.now(LOCAL_TZ)
    tz_name = now.strftime("%Z")  # PDT or PST
    return Panel(
        Align.center(
            Text(f"Claude Code Usage Monitor  |  {now.strftime('%Y-%m-%d %H:%M:%S')} {tz_name}", style="bold cyan")
        ),
        style="cyan",
        height=3,
    )


def build_token_panel(today_sessions, rolling_sessions):
    today_in, today_out, today_cr, today_cc = aggregate_tokens(today_sessions)
    today_total = today_in + today_out + today_cr + today_cc

    rolling_in, rolling_out, rolling_cr, rolling_cc = aggregate_tokens(rolling_sessions)
    rolling_total = rolling_in + rolling_out + rolling_cr + rolling_cc

    usage_pct = min(rolling_total / ESTIMATED_5H_TOKEN_LIMIT, 1.0) if ESTIMATED_5H_TOKEN_LIMIT > 0 else 0

    if usage_pct < 0.5:
        bar_style = "green"
    elif usage_pct < 0.8:
        bar_style = "yellow"
    else:
        bar_style = "red bold"

    today_cost = estimate_cost(today_sessions)
    rolling_cost = estimate_cost(rolling_sessions)

    lines = [
        f"[bold white]Today Total:[/]     {format_tokens(today_total)}  [bold yellow]{format_cost(today_cost)}[/]",
        f"  Input:           {format_tokens(today_in)}",
        f"  Output:          {format_tokens(today_out)}",
        f"  Cache Read:      {format_tokens(today_cr)}",
        f"  Cache Create:    {format_tokens(today_cc)}",
        "",
        f"[bold white]5h Window:[/]       {format_tokens(rolling_total)}  [bold yellow]{format_cost(rolling_cost)}[/]",
        "",
        f"[bold white]Rate Limit (est.):[/]  [{bar_style}]{usage_pct:.0%}[/]",
    ]

    bar = ProgressBar(total=100, completed=int(usage_pct * 100), style=bar_style, complete_style=bar_style)

    table = Table.grid(padding=(0, 1))
    table.add_row("\n".join(lines))
    table.add_row(bar)

    return Panel(table, title="Token Usage", border_style="green")


def build_burn_panel(today_sessions):
    rate = calc_burn_rate(today_sessions)
    inp, out, cr, cc = aggregate_tokens(today_sessions)
    today_total = inp + out + cr + cc
    today_cost = estimate_cost(today_sessions)

    # Cost per hour
    timestamps = []
    for s in today_sessions:
        timestamps.append(datetime.fromisoformat(s["start_time"]))
        timestamps.append(datetime.fromisoformat(s["last_activity"]))
    if timestamps:
        hours_active = max((datetime.now(timezone.utc) - min(timestamps)).total_seconds() / 3600, 0.1)
        cost_per_hr = today_cost / hours_active
    else:
        cost_per_hr = 0.0

    remaining = max(ESTIMATED_5H_TOKEN_LIMIT - today_total, 0)
    if rate > 0:
        hours_left = remaining / rate
        if hours_left > 24:
            time_left = "24h+"
        else:
            h = int(hours_left)
            m = int((hours_left - h) * 60)
            time_left = f"{h}h {m}m"
    else:
        time_left = "--"

    total_msgs = sum(s.get("user_message_count", 0) for s in today_sessions)
    total_tools = sum(s.get("tool_calls", 0) for s in today_sessions)

    # Find active sessions (activity in last 10 minutes)
    ten_min_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
    active = [
        s for s in today_sessions
        if datetime.fromisoformat(s["last_activity"]) >= ten_min_ago
    ]

    lines = [
        f"[bold white]Burn Rate:[/]      {format_tokens(int(rate))}/hr  [bold yellow]{format_cost(cost_per_hr)}/hr[/]",
        f"[bold white]Est. Remaining:[/] {time_left} until limit",
        "",
        f"[bold white]Sessions Today:[/] {len(today_sessions)}",
        f"[bold white]Active Now:[/]     [bold green]{len(active)}[/]" if active else f"[bold white]Active Now:[/]     [dim]0[/]",
        f"[bold white]Messages:[/]       {total_msgs}",
        f"[bold white]Tool Calls:[/]     {total_tools}",
    ]

    return Panel("\n".join(lines), title="Burn Rate & Activity", border_style="yellow")


def build_projects_panel(today_sessions, all_sessions):
    # Only show projects with activity today
    today_by_project = {}
    for s in today_sessions:
        name = s.get("project_name", "unknown")
        if name not in today_by_project:
            today_by_project[name] = []
        today_by_project[name].append(s)

    # Get all-time totals only for projects active today
    all_by_project = {}
    for s in all_sessions:
        name = s.get("project_name", "unknown")
        if name in today_by_project:
            if name not in all_by_project:
                all_by_project[name] = []
            all_by_project[name].append(s)

    table = Table(expand=True)
    table.add_column("Project", style="cyan")
    table.add_column("Today Tokens", justify="right", style="bold")
    table.add_column("Today Cost", justify="right", style="yellow")
    table.add_column("All Time Tokens", justify="right", style="dim bold")
    table.add_column("All Time Cost", justify="right", style="dim yellow")
    table.add_column("Models", style="dim")

    def sort_key(name):
        sessions = today_by_project.get(name, [])
        return -sum(s.get("input_tokens", 0) + s.get("output_tokens", 0) + s.get("cache_read_tokens", 0) + s.get("cache_create_tokens", 0) for s in sessions)

    for name in sorted(today_by_project.keys(), key=sort_key):
        today_s = today_by_project[name]
        all_s = all_by_project.get(name, [])

        today_tok = sum(s.get("input_tokens", 0) + s.get("output_tokens", 0) + s.get("cache_read_tokens", 0) + s.get("cache_create_tokens", 0) for s in today_s)
        all_tok = sum(s.get("input_tokens", 0) + s.get("output_tokens", 0) + s.get("cache_read_tokens", 0) + s.get("cache_create_tokens", 0) for s in all_s)

        today_cost = estimate_cost(today_s)
        all_cost = estimate_cost(all_s)

        # Collect models used today for this project
        project_models = set()
        for s in today_s:
            project_models.update(s.get("models", []))
        # Shorten model names: "claude-opus-4-6" -> "opus 4.6"
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
        table.add_row("[dim]No sessions today[/]", "", "", "", "", "")

    return Panel(table, title="Project Breakdown (Today + All Time)", border_style="blue")


def build_recent_panel(sessions):
    sorted_sessions = sorted(sessions, key=lambda s: s.get("last_activity", ""), reverse=True)[:7]

    table = Table(expand=True)
    table.add_column("Last Active", style="dim")
    table.add_column("Project", style="cyan")
    table.add_column("Duration", justify="right")
    table.add_column("Msgs", justify="right")
    table.add_column("Tokens", justify="right", style="bold")
    table.add_column("Cost", justify="right", style="yellow")

    for s in sorted_sessions:
        last = datetime.fromisoformat(s["last_activity"]).astimezone(LOCAL_TZ)
        dur = s.get("duration_minutes", 0)
        hours = dur // 60
        mins = dur % 60
        dur_str = f"{hours}h {mins}m" if hours > 0 else f"{mins}m"
        total = s.get("input_tokens", 0) + s.get("output_tokens", 0) + s.get("cache_read_tokens", 0) + s.get("cache_create_tokens", 0)
        msgs = s.get("user_message_count", 0)
        cost = estimate_cost([s])

        # Highlight if active in last 10 min
        ten_min_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
        last_utc = datetime.fromisoformat(s["last_activity"])
        style = "bold green" if last_utc >= ten_min_ago else ""

        table.add_row(
            Text(last.strftime("%m/%d %I:%M%p"), style=style),
            Text(s.get("project_name", "?"), style=style or "cyan"),
            dur_str,
            str(msgs),
            format_tokens(total),
            format_cost(cost),
        )

    return Panel(table, title="Recent Sessions", border_style="magenta")


def build_dashboard():
    all_sessions = scan_live_sessions()
    today_sessions = filter_today(all_sessions)
    rolling_sessions = filter_rolling_5h(all_sessions)

    layout = Layout()
    layout.split_column(
        Layout(build_header(), name="header", size=3),
        Layout(name="top", size=13),
        Layout(name="bottom"),
    )
    layout["top"].split_row(
        Layout(build_token_panel(today_sessions, rolling_sessions), name="tokens"),
        Layout(build_burn_panel(today_sessions), name="burn"),
    )
    layout["bottom"].split_row(
        Layout(build_projects_panel(today_sessions, all_sessions), name="projects"),
        Layout(build_recent_panel(all_sessions), name="recent"),
    )
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
