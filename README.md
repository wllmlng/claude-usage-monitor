# claude-usage-monitor
A live terminal dashboard that tracks your Claude Code token usage in real time.
Reads session data directly from `~/.claude/projects/` JSONL logs — no API keys or configuration needed.

## Features

- **Token Usage** — Today, weekly, and monthly totals with cost estimates and per-type token breakdown
- **Burn Rate & Activity** — Tokens/hr, cost/hr, active session count, hourly bar chart
- **Monthly Calendar** — Daily cost heatmap with projected monthly spend
- **Project Breakdown** — Per-project token and cost totals (today + all time), models used
- **Recent Sessions** — Last 6 sessions with duration, message count, tokens, and cost
- **Last Prompt** — Most recent prompt per active project with token and cost breakdown
- **Header** — Current time, date, and timezone

Cost estimates use per-model API pricing (Opus, Sonnet, Haiku) and are updated per message — not a flat session rate.

> **Note:** The Last Prompt panel displays up to 80 characters of your most recent prompt per project. Run in a private terminal if needed.

<img width="1728" height="655" alt="Screenshot 2026-04-06 at 16 26 18" src="https://github.com/user-attachments/assets/2078c9e1-f3c5-4f3e-aed1-90adf201bb3a" />

## Installation

Requires Python 3.11+.

```bash
git clone https://github.com/wllmlng/claude-usage-monitor.git
cd claude-usage-monitor
pip install -e .
```

Then run:

```bash
claude-monitor
```

Press `Ctrl+C` to exit.
