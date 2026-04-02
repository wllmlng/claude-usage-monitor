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
from rich.columns import Columns

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

SPARK_CHARS = "▁▂▃▄▅▆▇█"


def sparkline(values, width=24):
    """Render a sparkline string from a list of numbers."""
    if not values or max(values) == 0:
        return "▁" * width
    mx = max(values)
    # Pad or truncate to width
    if len(values) < width:
        values = [0] * (width - len(values)) + values
    elif len(values) > width:
        values = values[-width:]
    return "".join(SPARK_CHARS[min(int(v / mx * 7), 7)] if mx > 0 else "▁" for v in values)


def horizontal_bar(parts, width=40):
    """Render a colored horizontal stacked bar from [(value, color, label), ...]."""
    total = sum(v for v, _, _ in parts)
    if total == 0:
        return Text("▒" * width, style="dim")
    bar = Text()
    for value, color, label in parts:
        segment_width = max(int(value / total * width), 1) if value > 0 else 0
        bar.append("█" * segment_width, style=color)
    # Fill remaining
    current = sum(max(int(v / total * width), 1) if v > 0 else 0 for v, _, _ in parts)
    if current < width:
        bar.append("░" * (width - current), style="dim")
    return bar


def estimate_cost(sessions):
    """Estimate what the usage would cost on API pricing."""
    total_cost = 0.0
    for s in sessions:
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
    """Scan JSONL conversation logs with caching."""
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

            cached = _session_cache.get(path_key)
            if cached and cached[0] == mtime and cached[1] == size:
                sessions.append(cached[2])
                continue

            session = parse_jsonl_session(jsonl_path, project_dir.name)
            if session:
                _session_cache[path_key] = (mtime, size, session)
                sessions.append(session)

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
    hourly_tokens = {}  # hour (int, local tz) -> total tokens
    last_user_prompt = None
    last_prompt_response_tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
    tracking_last_prompt = False

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
                        last_user_prompt = content
                        last_prompt_response_tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
                        tracking_last_prompt = True

                if role == "assistant":
                    assistant_messages += 1
                    model = msg.get("model", "")
                    if model:
                        models_used.add(model)

                    msg_input = usage.get("input_tokens", 0)
                    msg_output = usage.get("output_tokens", 0)
                    msg_cache_r = usage.get("cache_read_input_tokens", 0)
                    msg_cache_c = usage.get("cache_creation_input_tokens", 0)

                    input_tokens += msg_input
                    output_tokens += msg_output
                    cache_read += msg_cache_r
                    cache_create += msg_cache_c

                    if tracking_last_prompt:
                        last_prompt_response_tokens["input"] += msg_input
                        last_prompt_response_tokens["output"] += msg_output
                        last_prompt_response_tokens["cache_read"] += msg_cache_r
                        last_prompt_response_tokens["cache_create"] += msg_cache_c

                    # Track hourly usage
                    if ts_str:
                        hour = datetime.fromisoformat(ts_str).astimezone(LOCAL_TZ).hour
                        hourly_tokens[hour] = hourly_tokens.get(hour, 0) + msg_input + msg_output + msg_cache_r + msg_cache_c

                    for block in msg.get("content", []):
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_calls += 1

    except OSError:
        return None

    if first_ts is None:
        return None

    # Dir names encode the full path with / replaced by -, e.g. "-Users-foo-Documents-my-project"
    # Reconstruct the real path, then take the last component to preserve hyphens in folder names
    home_prefix = str(Path.home()).replace("/", "-").lstrip("-")  # e.g. "Users-williamleung"
    name = project_dir_name.lstrip("-")
    if name.startswith(home_prefix + "-"):
        name = name[len(home_prefix) + 1:]  # strip "Users-williamleung-"
        # Strip one more path segment (Documents, Desktop, etc.)
        if "-" in name:
            name = name.split("-", 1)[1]  # strip "Documents-" or "Desktop-"
    project_name = name or project_dir_name

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
        "hourly_tokens": hourly_tokens,
        "last_prompt": last_user_prompt,
        "last_prompt_tokens": last_prompt_response_tokens,
    }


def filter_today(sessions):
    """Filter sessions that have activity today (Pacific time)."""
    today = datetime.now(LOCAL_TZ).date()
    return [
        s for s in sessions
        if datetime.fromisoformat(s["last_activity"]).astimezone(LOCAL_TZ).date() == today
        or datetime.fromisoformat(s["start_time"]).astimezone(LOCAL_TZ).date() == today
    ]


def filter_this_week(sessions):
    """Filter sessions with activity this week (Monday-Sunday, Pacific time)."""
    now = datetime.now(LOCAL_TZ)
    monday = (now - timedelta(days=now.weekday())).date()
    sunday = monday + timedelta(days=6)
    return [
        s for s in sessions
        if monday <= datetime.fromisoformat(s["last_activity"]).astimezone(LOCAL_TZ).date() <= sunday
        or monday <= datetime.fromisoformat(s["start_time"]).astimezone(LOCAL_TZ).date() <= sunday
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


def aggregate_hourly(sessions):
    """Merge hourly token data across sessions into a 24-hour array."""
    hourly = [0] * 24
    for s in sessions:
        for hour_str, tokens in s.get("hourly_tokens", {}).items():
            hour = int(hour_str)
            if 0 <= hour < 24:
                hourly[hour] += tokens
    return hourly


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
    tz_name = now.strftime("%Z")
    return Panel(
        Align.center(
            Text(f"Claude Code Usage Monitor  |  {now.strftime('%Y-%m-%d %H:%M:%S')} {tz_name}", style="bold cyan")
        ),
        style="cyan",
        height=3,
    )


def build_token_panel(today_sessions, rolling_sessions, week_sessions):
    today_in, today_out, today_cr, today_cc = aggregate_tokens(today_sessions)
    today_total = today_in + today_out + today_cr + today_cc

    week_in, week_out, week_cr, week_cc = aggregate_tokens(week_sessions)
    week_total = week_in + week_out + week_cr + week_cc

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
    week_cost = estimate_cost(week_sessions)
    rolling_cost = estimate_cost(rolling_sessions)

    # Token type breakdown bar
    breakdown = horizontal_bar([
        (today_in, "bright_blue", "input"),
        (today_out, "bright_green", "output"),
        (today_cr, "bright_cyan", "cache read"),
        (today_cc, "bright_magenta", "cache create"),
    ], width=36)

    # Left column: totals
    left = Text()
    left.append("Today ", style="bold white")
    left.append(f"{format_tokens(today_total)} ", style="bold white")
    left.append(f"{format_cost(today_cost)}\n", style="bold yellow")
    left.append(f" In:  {format_tokens(today_in)}\n")
    left.append(f" Out: {format_tokens(today_out)}\n")
    left.append(f" C/R: {format_tokens(today_cr)}\n")
    left.append(f" C/W: {format_tokens(today_cc)}\n\n")
    left.append("Week ", style="bold white")
    left.append(f"{format_tokens(week_total)} ", style="bold white")
    left.append(f"{format_cost(week_cost)}\n", style="bold yellow")
    left.append(f" In:  {format_tokens(week_in)}\n")
    left.append(f" Out: {format_tokens(week_out)}\n")
    left.append(f" C/R: {format_tokens(week_cr)}\n")
    left.append(f" C/W: {format_tokens(week_cc)}\n")

    # Right column: breakdown bar + rate limit
    right = Text()
    right.append("Today Breakdown:\n", style="bold white")
    right.append("  ")
    right.append_text(breakdown)
    right.append("\n  ")
    right.append("██", style="bright_blue")
    right.append(" in ", style="dim")
    right.append("██", style="bright_green")
    right.append(" out\n  ", style="dim")
    right.append("██", style="bright_cyan")
    right.append(" cache-r ", style="dim")
    right.append("██", style="bright_magenta")
    right.append(" cache-w\n\n", style="dim")
    right.append(f"5h Window:\n", style="bold white")
    right.append(f"  {format_tokens(rolling_total)}  ", style="bold white")
    right.append(f"{format_cost(rolling_cost)}\n\n", style="bold yellow")
    right.append("Rate Limit (est.):\n", style="bold white")
    right.append(f"  {usage_pct:.0%}\n", style=bar_style)

    bar = ProgressBar(total=100, completed=int(usage_pct * 100), style=bar_style, complete_style=bar_style)

    grid = Table.grid(padding=(0, 2))
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)
    grid.add_row(left, right)

    outer = Table.grid(padding=(0, 1))
    outer.add_row(grid)
    outer.add_row(bar)

    return Panel(outer, title="Token Usage", border_style="green")


def build_burn_panel(today_sessions):
    rate = calc_burn_rate(today_sessions)
    inp, out, cr, cc = aggregate_tokens(today_sessions)
    today_total = inp + out + cr + cc
    today_cost = estimate_cost(today_sessions)

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

    ten_min_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
    active = [
        s for s in today_sessions
        if datetime.fromisoformat(s["last_activity"]) >= ten_min_ago
    ]

    # Hourly sparkline
    hourly = aggregate_hourly(today_sessions)
    current_hour = datetime.now(LOCAL_TZ).hour
    # Show from hour 6 (6am) to current hour
    start_hour = 6
    end_hour = current_hour + 1
    visible_hours = hourly[start_hour:end_hour] if end_hour > start_hour else hourly[start_hour:]

    # Left column: stats
    left = Text()
    left.append(f"Burn Rate:      ", style="bold white")
    left.append(f"{format_tokens(int(rate))}/hr\n", style="bold white")
    left.append(f"                ", style="bold white")
    left.append(f"{format_cost(cost_per_hr)}/hr\n", style="bold yellow")
    left.append(f"Est. Remaining: {time_left}\n\n", style="bold white")
    left.append(f"Sessions Today: {len(today_sessions)}\n", style="bold white")
    if active:
        left.append(f"Active Now:     {len(active)}\n", style="bold green")
    else:
        left.append(f"Active Now:     0\n", style="dim")
    left.append(f"Messages:       {total_msgs}\n", style="bold white")
    left.append(f"Tool Calls:     {total_tools}\n", style="bold white")

    # Right column: vertical hourly bar chart (takes more space)
    right = Text()
    right.append("Hourly Usage:\n", style="bold white")
    max_val = max(visible_hours) if visible_hours and max(visible_hours) > 0 else 1
    chart_height = 3
    for row in range(chart_height, 0, -1):
        threshold = max_val * row / chart_height
        right.append(" ", style="dim")
        for val in visible_hours:
            if val >= threshold and val > 0:
                right.append("██", style="bright_yellow")
            else:
                right.append("  ", style="dim")
            right.append(" ", style="dim")
        right.append("\n")
    # Hour labels — every hour
    right.append(" ", style="dim")
    for i in range(len(visible_hours)):
        h = start_hour + i
        display_h = h if h <= 12 else h - 12
        suffix = "a" if h < 12 else "p"
        label = f"{display_h}{suffix}"
        right.append(f"{label:<3}", style="dim")
    right.append("\n Peak: ", style="dim")
    right.append(f"{format_tokens(max_val)}", style="bold white")

    grid = Table.grid(padding=(0, 1))
    grid.add_column(width=30)
    grid.add_column(ratio=1)
    grid.add_row(left, right)

    return Panel(grid, title="Burn Rate & Activity", border_style="yellow")


def build_projects_panel(today_sessions, all_sessions):
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


def build_last_prompt_panel(today_sessions):
    """Show the last prompt per active project with token usage."""
    # Get the most recent session per project
    by_project = {}
    for s in today_sessions:
        name = s.get("project_name", "unknown")
        if name not in by_project or s["last_activity"] > by_project[name]["last_activity"]:
            by_project[name] = s

    table = Table(expand=True)
    table.add_column("Project", style="cyan", width=20)
    table.add_column("Last Prompt", style="white", ratio=1)
    table.add_column("Tokens", justify="right", style="bold", width=10)
    table.add_column("Cost", justify="right", style="yellow", width=8)

    sorted_projects = sorted(by_project.items(), key=lambda x: x[1]["last_activity"], reverse=True)
    for name, s in sorted_projects:
        prompt = s.get("last_prompt") or ""
        # Truncate to ~80 chars with ellipsis
        if len(prompt) > 80:
            prompt = prompt[:77] + "..."
        prompt = prompt.replace("\n", " ")

        tok = s.get("last_prompt_tokens", {})
        total = tok.get("input", 0) + tok.get("output", 0) + tok.get("cache_read", 0) + tok.get("cache_create", 0)
        cost = (
            tok.get("input", 0) / 1_000_000 * 5.0
            + tok.get("output", 0) / 1_000_000 * 25.0
            + tok.get("cache_read", 0) / 1_000_000 * 0.5
            + tok.get("cache_create", 0) / 1_000_000 * 6.25
        )

        table.add_row(name, prompt, format_tokens(total), format_cost(cost))

    if not by_project:
        table.add_row("[dim]No sessions today[/]", "", "", "")

    return Panel(table, title="Last Prompt per Project", border_style="bright_white")


def build_dashboard():
    all_sessions = scan_live_sessions()
    today_sessions = filter_today(all_sessions)
    week_sessions = filter_this_week(all_sessions)
    rolling_sessions = filter_rolling_5h(all_sessions)

    layout = Layout()
    layout.split_column(
        Layout(build_header(), name="header", size=3),
        Layout(name="top"),
        Layout(name="middle"),
        Layout(name="bottom", size=min(len(set(s["project_name"] for s in today_sessions)) + 5, 12)),
    )
    layout["top"].split_row(
        Layout(build_token_panel(today_sessions, rolling_sessions, week_sessions), name="tokens"),
        Layout(build_burn_panel(today_sessions), name="burn"),
    )
    layout["middle"].split_row(
        Layout(build_projects_panel(today_sessions, all_sessions), name="projects"),
        Layout(build_recent_panel(all_sessions), name="recent"),
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
