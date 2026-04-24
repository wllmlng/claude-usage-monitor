from pathlib import Path
from zoneinfo import ZoneInfo

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
SESSION_META_DIR = CLAUDE_DIR / "usage-data" / "session-meta"
LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# API pricing per million tokens (for "what would this cost" estimates)
# Source: https://platform.claude.com/docs/en/about-claude/pricing
# Last verified: 2026-04-24
MODEL_PRICING = {
    "claude-opus-4-7":   {"input": 5.0,  "output": 25.0,  "cache_read": 0.50, "cache_create": 6.25},
    "claude-opus-4-6":   {"input": 5.0,  "output": 25.0,  "cache_read": 0.50, "cache_create": 6.25},
    "claude-opus-4-5":   {"input": 5.0,  "output": 25.0,  "cache_read": 0.50, "cache_create": 6.25},
    "claude-opus-4-1":   {"input": 15.0, "output": 75.0,  "cache_read": 1.50, "cache_create": 18.75},
    "claude-opus-4":     {"input": 15.0, "output": 75.0,  "cache_read": 1.50, "cache_create": 18.75},
    "claude-opus-3":     {"input": 15.0, "output": 75.0,  "cache_read": 1.50, "cache_create": 18.75},
    "claude-sonnet-4-6": {"input": 3.0,  "output": 15.0,  "cache_read": 0.30, "cache_create": 3.75},
    "claude-sonnet-4-5": {"input": 3.0,  "output": 15.0,  "cache_read": 0.30, "cache_create": 3.75},
    "claude-sonnet-4":   {"input": 3.0,  "output": 15.0,  "cache_read": 0.30, "cache_create": 3.75},
    "claude-sonnet-3-7": {"input": 3.0,  "output": 15.0,  "cache_read": 0.30, "cache_create": 3.75},
    "claude-haiku-4-5":  {"input": 1.0,  "output": 5.0,   "cache_read": 0.10, "cache_create": 1.25},
    "claude-haiku-3-5":  {"input": 0.80, "output": 4.0,   "cache_read": 0.08, "cache_create": 1.00},
    "claude-haiku-3":    {"input": 0.25, "output": 1.25,  "cache_read": 0.03, "cache_create": 0.30},
}

# Keys sorted longest-first so more specific models (e.g. claude-opus-4-6) match
# before shorter prefixes (e.g. claude-opus-4) when doing substring lookups.
_PRICING_KEYS_BY_SPECIFICITY = sorted(MODEL_PRICING, key=len, reverse=True)

def get_model_pricing(model_name: str) -> dict:
    """Return pricing for the closest matching model, defaulting to Sonnet 4.6."""
    name = model_name.lower()
    for key in _PRICING_KEYS_BY_SPECIFICITY:
        if key in name:
            return MODEL_PRICING[key]
    return MODEL_PRICING["claude-sonnet-4-6"]
