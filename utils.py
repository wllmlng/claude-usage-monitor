from rich.text import Text

from constants import MODEL_PRICING


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


def format_tokens(n):
    """Human-readable token count."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)
