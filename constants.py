from pathlib import Path
from zoneinfo import ZoneInfo

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
SESSION_META_DIR = CLAUDE_DIR / "usage-data" / "session-meta"
LOCAL_TZ = ZoneInfo("America/Los_Angeles")

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
