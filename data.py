"""Session parsing, caching, filtering, and aggregation."""

import calendar
import json
from datetime import date as date_type, datetime, timezone, timedelta
from pathlib import Path

from constants import PROJECTS_DIR, LOCAL_TZ, get_model_pricing
from utils import cost_for_tokens


def parse_ts(s):
    """Parse an ISO timestamp, accepting trailing 'Z' on older Python versions."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def add_months(year, month, offset):
    """Return (year, month) shifted by `offset` months."""
    total = year * 12 + (month - 1) + offset
    y, m = divmod(total, 12)
    return y, m + 1


# Bump this when the parsed session schema changes to invalidate stale caches
_CACHE_VERSION = 6

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
            if cached and cached[0] == mtime and cached[1] == size and cached[2].get("_cache_version") == _CACHE_VERSION:
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
    hourly_tokens = {}
    daily_tokens = {}
    daily_tokens_by_model = {}
    tokens_by_model = {}
    daily_messages = {}
    last_user_prompt = None
    last_prompt_response_tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
    last_prompt_model = None
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
                    ts = parse_ts(ts_str)
                    if first_ts is None or ts < first_ts:
                        first_ts = ts
                    if last_ts is None or ts > last_ts:
                        last_ts = ts

                msg = entry.get("message", {})
                role = msg.get("role")
                usage = msg.get("usage", {})

                if role == "user" and entry.get("type") == "user":
                    content = msg.get("content")
                    prompt_text = None
                    if isinstance(content, str):
                        prompt_text = content
                    elif isinstance(content, list) and content:
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                prompt_text = block.get("text", "")
                                break
                            elif isinstance(block, str):
                                prompt_text = block
                                break
                    if prompt_text is not None:
                        user_messages += 1
                        if not prompt_text.strip().startswith("/"):
                            last_user_prompt = prompt_text
                        last_prompt_response_tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
                        tracking_last_prompt = True
                        if ts_str:
                            msg_day = parse_ts(ts_str).astimezone(LOCAL_TZ).date().isoformat()
                            daily_messages[msg_day] = daily_messages.get(msg_day, 0) + 1

                if role == "assistant":
                    assistant_messages += 1
                    model = msg.get("model", "")
                    if model and model != "<synthetic>":
                        models_used.add(model)

                    msg_input = usage.get("input_tokens", 0)
                    msg_output = usage.get("output_tokens", 0)
                    msg_cache_r = usage.get("cache_read_input_tokens", 0)
                    msg_cache_c = usage.get("cache_creation_input_tokens", 0)

                    input_tokens += msg_input
                    output_tokens += msg_output
                    cache_read += msg_cache_r
                    cache_create += msg_cache_c

                    real_model = model if model and model != "<synthetic>" else None
                    model_key = real_model or last_prompt_model or "unknown"
                    if model_key not in tokens_by_model:
                        tokens_by_model[model_key] = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
                    tokens_by_model[model_key]["input"] += msg_input
                    tokens_by_model[model_key]["output"] += msg_output
                    tokens_by_model[model_key]["cache_read"] += msg_cache_r
                    tokens_by_model[model_key]["cache_create"] += msg_cache_c

                    if tracking_last_prompt:
                        last_prompt_response_tokens["input"] += msg_input
                        last_prompt_response_tokens["output"] += msg_output
                        last_prompt_response_tokens["cache_read"] += msg_cache_r
                        last_prompt_response_tokens["cache_create"] += msg_cache_c
                        if real_model:
                            last_prompt_model = real_model

                    if ts_str:
                        local_dt = parse_ts(ts_str).astimezone(LOCAL_TZ)
                        hour_key = f"{local_dt.date().isoformat()}:{local_dt.hour}"
                        msg_total = msg_input + msg_output + msg_cache_r + msg_cache_c
                        hourly_tokens[hour_key] = hourly_tokens.get(hour_key, 0) + msg_total

                        day_key = local_dt.date().isoformat()
                        if day_key not in daily_tokens:
                            daily_tokens[day_key] = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
                        daily_tokens[day_key]["input"] += msg_input
                        daily_tokens[day_key]["output"] += msg_output
                        daily_tokens[day_key]["cache_read"] += msg_cache_r
                        daily_tokens[day_key]["cache_create"] += msg_cache_c

                        if day_key not in daily_tokens_by_model:
                            daily_tokens_by_model[day_key] = {}
                        if model_key not in daily_tokens_by_model[day_key]:
                            daily_tokens_by_model[day_key][model_key] = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
                        daily_tokens_by_model[day_key][model_key]["input"] += msg_input
                        daily_tokens_by_model[day_key][model_key]["output"] += msg_output
                        daily_tokens_by_model[day_key][model_key]["cache_read"] += msg_cache_r
                        daily_tokens_by_model[day_key][model_key]["cache_create"] += msg_cache_c

                    for block in msg.get("content", []):
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_calls += 1

    except OSError:
        return None

    if first_ts is None:
        return None

    home_prefix = str(Path.home()).replace("/", "-").lstrip("-")
    name = project_dir_name.lstrip("-")
    if name.startswith(home_prefix + "-"):
        name = name[len(home_prefix) + 1:]
        if "-" in name:
            name = name.split("-", 1)[1]
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
        "tokens_by_model": tokens_by_model,
        "hourly_tokens": hourly_tokens,
        "last_prompt": last_user_prompt,
        "last_prompt_model": last_prompt_model,
        "last_prompt_tokens": last_prompt_response_tokens,
        "daily_tokens": daily_tokens,
        "daily_tokens_by_model": daily_tokens_by_model,
        "daily_messages": daily_messages,
        "_cache_version": _CACHE_VERSION,
    }


def filter_for_date(sessions, target_date):
    """Filter sessions that have activity on a given local date."""
    return [
        s for s in sessions
        if target_date.isoformat() in s.get("daily_tokens", {})
        or target_date.isoformat() in s.get("daily_messages", {})
        or datetime.fromisoformat(s["last_activity"]).astimezone(LOCAL_TZ).date() == target_date
        or datetime.fromisoformat(s["start_time"]).astimezone(LOCAL_TZ).date() == target_date
    ]


def resolve_view_date(sessions, year, month):
    """Pick a representative day for the given month.

    Returns the most recent day with activity in that month, or the last day
    of the month if there is none. For the current month, returns today.
    """
    today = datetime.now(LOCAL_TZ).date()
    if year == today.year and month == today.month:
        return today
    days_in_month = calendar.monthrange(year, month)[1]
    last_day = date_type(year, month, days_in_month)
    best = None
    for s in sessions:
        for day_str, tok in s.get("daily_tokens", {}).items():
            try:
                d = date_type.fromisoformat(day_str)
            except ValueError:
                continue
            if d.year != year or d.month != month:
                continue
            total = tok.get("input", 0) + tok.get("output", 0) + tok.get("cache_read", 0) + tok.get("cache_create", 0)
            if total <= 0:
                continue
            if best is None or d > best:
                best = d
    return best or last_day


def aggregate_tokens(sessions):
    """Sum tokens across sessions."""
    total_input = sum(s.get("input_tokens", 0) for s in sessions)
    total_output = sum(s.get("output_tokens", 0) for s in sessions)
    total_cache_read = sum(s.get("cache_read_tokens", 0) for s in sessions)
    total_cache_create = sum(s.get("cache_create_tokens", 0) for s in sessions)
    return total_input, total_output, total_cache_read, total_cache_create


def aggregate_hourly(sessions, target_date=None):
    """Merge hourly token data across sessions into a 24-hour array.

    If target_date is provided, only include tokens from that date.
    hourly_tokens keys are "YYYY-MM-DD:HH" format.
    """
    if target_date is None:
        target_date = datetime.now(LOCAL_TZ).date()
    date_prefix = target_date.isoformat() + ":"
    hourly = [0] * 24
    for s in sessions:
        for key, tokens in s.get("hourly_tokens", {}).items():
            if key.startswith(date_prefix):
                hour = int(key.split(":")[1])
                if 0 <= hour < 24:
                    hourly[hour] += tokens
    return hourly


def aggregate_tokens_for_dates(sessions, start_date, end_date):
    """Sum only tokens that occurred within the date range using daily_tokens."""
    total_in, total_out, total_cr, total_cc = 0, 0, 0, 0
    if start_date == end_date:
        key = start_date.isoformat()
        for s in sessions:
            tok = s.get("daily_tokens", {}).get(key)
            if tok:
                total_in += tok["input"]
                total_out += tok["output"]
                total_cr += tok["cache_read"]
                total_cc += tok["cache_create"]
        return total_in, total_out, total_cr, total_cc
    for s in sessions:
        for day_str, tok in s.get("daily_tokens", {}).items():
            d = date_type.fromisoformat(day_str)
            if start_date <= d <= end_date:
                total_in += tok["input"]
                total_out += tok["output"]
                total_cr += tok["cache_read"]
                total_cc += tok["cache_create"]
    return total_in, total_out, total_cr, total_cc


def estimate_cost_for_dates(sessions, start_date, end_date):
    """Estimate cost for tokens within a date range, priced per model per day."""
    total_cost = 0.0
    if start_date == end_date:
        key = start_date.isoformat()
        for s in sessions:
            daily_by_model = s.get("daily_tokens_by_model", {}).get(key)
            if daily_by_model:
                for model, tok in daily_by_model.items():
                    total_cost += cost_for_tokens(tok, get_model_pricing(model))
            else:
                tok = s.get("daily_tokens", {}).get(key)
                if tok:
                    total_cost += cost_for_tokens(tok, get_model_pricing(s.get("last_prompt_model", "") or ""))
        return total_cost
    for s in sessions:
        daily_by_model = s.get("daily_tokens_by_model", {})
        if daily_by_model:
            for day_str, models_dict in daily_by_model.items():
                d = date_type.fromisoformat(day_str)
                if start_date <= d <= end_date:
                    for model, tok in models_dict.items():
                        total_cost += cost_for_tokens(tok, get_model_pricing(model))
        else:
            pricing = get_model_pricing(s.get("last_prompt_model", "") or "")
            for day_str, tok in s.get("daily_tokens", {}).items():
                d = date_type.fromisoformat(day_str)
                if start_date <= d <= end_date:
                    total_cost += cost_for_tokens(tok, pricing)
    return total_cost
