#!/usr/bin/env python3
"""Hourly traffic digest for barkeeps-ledger, posted to Discord.

The agent fetches the last hour of web traffic data across all sites
and writes a short digest to Discord.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    export AGENTSPAN_SERVER_URL=http://localhost:7001/api
    export DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
    python barkeeps/hourly_digest.py

Schedule hourly with cron:
    0 * * * * cd /path/to/agentspan-examples && python barkeeps/hourly_digest.py
"""

import os
import time
import requests
from conductor.ai.agents import Agent, AgentRuntime, tool

MODEL = os.environ.get("AGENTSPAN_LLM_MODEL", "anthropic/claude-haiku-4-5-20251001")
BARKEEPS_BASE = os.environ["BARKEEPS_BASE_URL"]
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]


@tool
def get_top_pages(window_seconds: int = 3600) -> str:
    """Fetch the most-visited pages across all sites in the given time window (seconds)."""
    r = requests.get(f"{BARKEEPS_BASE}/api/rankings", params={"window": window_seconds}, timeout=10)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return "No page visits recorded in this window."
    lines = [f"{row['hits']:4d}  {row['site']}{row['url']}" for row in rows[:20]]
    return "\n".join(lines)


@tool
def get_top_countries(window_seconds: int = 3600) -> str:
    """Fetch the top visitor countries in the given time window (seconds)."""
    r = requests.get(f"{BARKEEPS_BASE}/api/origins", params={"window": window_seconds}, timeout=10)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return "No origin data available."
    lines = [f"{row['hits']:4d}  {row['country']} ({row['code']})" for row in rows[:10]]
    return "\n".join(lines)


@tool
def get_hourly_trend() -> str:
    """Fetch the last 24 hours of hit counts to show traffic trend."""
    r = requests.get(f"{BARKEEPS_BASE}/api/hourly", timeout=10)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return "No hourly data available."
    now = int(time.time())
    recent = [row for row in rows if row["hour"] >= now - 86400]
    if not recent:
        recent = rows[-24:]
    lines = []
    for row in recent[-24:]:
        ts = time.strftime("%H:00", time.localtime(row["hour"]))
        bar = "#" * min(row["hits"], 40)
        lines.append(f"{ts}  {bar} ({row['hits']})")
    return "\n".join(lines)


@tool
def post_to_discord(message: str) -> str:
    """Post the digest message to Discord. Returns 'sent' on success."""
    payload = {"content": message, "username": "barkeeps-ledger"}
    r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    r.raise_for_status()
    return "sent"


agent = Agent(
    name="barkeeps_hourly_digest",
    model=MODEL,
    tools=[get_top_pages, get_top_countries, get_hourly_trend, post_to_discord],
    instructions="""You analyze web traffic data from barkeeps-ledger and post an hourly digest to Discord.

Steps:
1. Call get_hourly_trend() to see the last 24 hours traffic pattern.
2. Call get_top_pages(3600) to see what was popular in the last hour.
3. Call get_top_countries(3600) to see where visitors came from.
4. Compose a short Discord message (3-5 sentences, no headers) and call post_to_discord().

The message should:
- Start with a brief current-hour summary ("This hour: X hits across N sites")
- Name the top 2-3 pages by hits
- Note dominant geographies if anything stands out
- Mention any trend (busy/quiet compared to the past few hours)
- Be casual and factual, like a friendly ops update

Do not use markdown headers or bullet points — keep it conversational.""",
    max_turns=6,
)


if __name__ == "__main__":
    with AgentRuntime() as runtime:
        result = runtime.run(
            agent,
            "Fetch the latest barkeeps traffic data and post the hourly digest to Discord.",
        )
        if isinstance(result.output, dict):
            print(result.output.get("result", str(result.output)))
        else:
            print(result.output)
