from rich.panel import Panel
from rich.table import Table

from utils import format_tokens, format_cost


def build_last_prompt_panel(today_sessions):
    """Show the last prompt per active project with token usage."""
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
