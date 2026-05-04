from rich.text import Text

from constants import get_model_pricing


def horizontal_bar(parts, width=40):
    """Render a colored horizontal stacked bar from [(value, color, label), ...]."""
    total = sum(v for v, _, _ in parts)
    if total == 0:
        return Text("▒" * width, style="dim")
    bar = Text()
    for value, color, label in parts:
        segment_width = max(int(value / total * width), 1) if value > 0 else 0
        bar.append("█" * segment_width, style=color)
    current = sum(max(int(v / total * width), 1) if v > 0 else 0 for v, _, _ in parts)
    if current < width:
        bar.append("░" * (width - current), style="dim")
    return bar


def cost_for_tokens(tok, pricing):
    """Cost for a {input, output, cache_read, cache_create} dict at given pricing."""
    return (
        tok.get("input", 0) / 1_000_000 * pricing["input"]
        + tok.get("output", 0) / 1_000_000 * pricing["output"]
        + tok.get("cache_read", 0) / 1_000_000 * pricing["cache_read"]
        + tok.get("cache_create", 0) / 1_000_000 * pricing["cache_create"]
    )


def estimate_cost(sessions):
    """Estimate what the usage would cost on API pricing."""
    total_cost = 0.0
    for s in sessions:
        tokens_by_model = s.get("tokens_by_model", {})
        if tokens_by_model:
            for model, tok in tokens_by_model.items():
                total_cost += cost_for_tokens(tok, get_model_pricing(model))
        else:
            pricing = get_model_pricing(s.get("last_prompt_model", "") or "")
            tok = {
                "input": s.get("input_tokens", 0),
                "output": s.get("output_tokens", 0),
                "cache_read": s.get("cache_read_tokens", 0),
                "cache_create": s.get("cache_create_tokens", 0),
            }
            total_cost += cost_for_tokens(tok, pricing)
    return total_cost


def format_cost(cost):
    """Format cost as dollars."""
    if cost >= 1.0:
        return f"${cost:.2f}"
    return f"${cost:.3f}"


def format_tokens(n):
    """Format token count with K/M suffix."""
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)
