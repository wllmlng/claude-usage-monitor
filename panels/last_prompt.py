from rich.panel import Panel
from rich.table import Table

from utils import cost_for_tokens, format_tokens, format_cost, pricing_for_models


def build_last_prompt_panel(today_sessions, view_date=None, is_current=True):
    """Show the last prompt per active project with token usage."""
    day_label = "Today" if is_current else (view_date.strftime("%b %-d") if view_date else "Today")
    by_project = {}
    for s in today_sessions:
        name = s.get("project_name", "unknown")
        if name not in by_project or s["last_activity"] > by_project[name]["last_activity"]:
            by_project[name] = s

    table = Table(expand=True)
    table.add_column("Project", style="cyan", width=20)
    table.add_column("Last Prompt", style="white", ratio=1)
    table.add_column("C/R", justify="right", style="bright_cyan", width=8)
    table.add_column("Model", style="bright_white", width=16)
    table.add_column("Tokens", justify="right", style="bold", width=10)
    table.add_column("Cost", justify="right", style="yellow", width=8)

    sorted_projects = sorted(by_project.items(), key=lambda x: x[1]["last_activity"], reverse=True)
    for name, s in sorted_projects:
        prompt = s.get("last_prompt") or ""
        if len(prompt) > 80:
            prompt = prompt[:77] + "..."
        prompt = prompt.replace("\n", " ")

        tok = s.get("last_prompt_tokens", {})
        total = tok.get("input", 0) + tok.get("output", 0) + tok.get("cache_read", 0) + tok.get("cache_create", 0)
        cost = cost_for_tokens(tok, pricing_for_models([s.get("last_prompt_model", "") or ""]))

        cache_read = tok.get("cache_read", 0)
        model = s.get("last_prompt_model", "—") or "—"
        # Extract short model name with version (e.g., "claude-opus-4-6" → "opus-4.6")
        if model != "—" and model.startswith("claude-"):
            parts = model.replace("claude-", "").split("-")
            if len(parts) > 1:
                model = parts[0] + "-" + ".".join(parts[1:3])
            else:
                model = parts[0]
        table.add_row(name, prompt, format_tokens(cache_read), model, format_tokens(total), format_cost(cost))

    if not by_project:
        table.add_row(f"[dim]No sessions on {day_label}[/]", "", "", "", "")

    title = "Last Prompt per Project" if is_current else f"Last Prompt per Project ({day_label})"
    return Panel(table, title=title, border_style="bright_white")
