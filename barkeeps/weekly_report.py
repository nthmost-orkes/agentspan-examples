#!/usr/bin/env python3
"""Weekly traffic narrative for barkeeps-ledger, posted to Discord.

The agent synthesizes a week of traffic data into a readable narrative
covering trends, top content, and geographic reach.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    export AGENTSPAN_SERVER_URL=http://localhost:7001/api
    export DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
    python barkeeps/weekly_report.py

Schedule weekly with cron (Mondays at 9am):
    0 9 * * 1 cd /path/to/agentspan-examples && python barkeeps/weekly_report.py
"""

import os
import time
import requests
from conductor.ai.agents import Agent, AgentRuntime, tool

MODEL = os.environ.get("AGENTSPAN_LLM_MODEL", "anthropic/claude-haiku-4-5-20251001")
BARKEEPS_BASE = os.environ.get("BARKEEPS_BASE_URL", "https://bar.nthmost.net")
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]

WEEK_SECONDS = 604800


@tool
def get_weekly_hourly_trend() -> str:
    """Fetch 7 days of hourly traffic to see daily patterns and peaks."""
    r = requests.get(f"{BARKEEPS_BASE}/api/hourly", timeout=10)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return "No hourly data available."

    now = int(time.time())
    week_rows = [row for row in rows if row["hour"] >= now - WEEK_SECONDS]
    if not week_rows:
        week_rows = rows

    # Summarize by day-of-week and find daily totals
    daily_totals: dict = {}
    for row in week_rows:
        day = time.strftime("%a %m/%d", time.localtime(row["hour"]))
        daily_totals[day] = daily_totals.get(day, 0) + row["hits"]

    total = sum(daily_totals.values())
    lines = [f"Total hits this week: {total}\n", "Daily breakdown:"]
    for day, hits in daily_totals.items():
        bar = "#" * min(hits // 2, 40)
        lines.append(f"  {day}: {hits:4d}  {bar}")

    peak_day = max(daily_totals, key=daily_totals.get) if daily_totals else "N/A"
    lines.append(f"\nPeak day: {peak_day} ({daily_totals.get(peak_day, 0)} hits)")
    return "\n".join(lines)


@tool
def get_weekly_top_pages() -> str:
    """Fetch the most-visited pages across the past 7 days."""
    r = requests.get(f"{BARKEEPS_BASE}/api/rankings", params={"window": WEEK_SECONDS}, timeout=10)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return "No ranking data for the week."
    lines = [f"{row['hits']:4d}  {row['site']}{row['url']}" for row in rows[:15]]
    return "\n".join(lines)


@tool
def get_weekly_countries() -> str:
    """Fetch the top visitor countries over the past 7 days."""
    r = requests.get(f"{BARKEEPS_BASE}/api/origins", params={"window": WEEK_SECONDS}, timeout=10)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return "No origin data for the week."
    lines = [f"{row['hits']:4d}  {row['country']} ({row['code']})" for row in rows[:15]]
    return "\n".join(lines)


@tool
def get_weekly_cities() -> str:
    """Fetch the top visitor cities over the past 7 days."""
    r = requests.get(f"{BARKEEPS_BASE}/api/cities", params={"window": WEEK_SECONDS}, timeout=10)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return "No city data for the week."
    lines = [f"{row['hits']:4d}  {row.get('city', '?')}, {row.get('country', '?')} ({row.get('code', '?')})" for row in rows[:15]]
    return "\n".join(lines)


@tool
def post_weekly_report(report: str) -> str:
    """Post the weekly narrative report to Discord.

    report should be a 150-250 word markdown-friendly summary.
    Returns 'sent' on success.
    """
    # Discord has a 2000-char message limit; split if needed
    chunks = [report[i:i+1900] for i in range(0, len(report), 1900)]
    for chunk in chunks:
        payload = {"content": chunk, "username": "barkeeps-ledger weekly"}
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        r.raise_for_status()
    return "sent"


agent = Agent(
    name="barkeeps_weekly_report",
    model=MODEL,
    tools=[get_weekly_hourly_trend, get_weekly_top_pages, get_weekly_countries, get_weekly_cities, post_weekly_report],
    instructions="""You write a weekly web traffic narrative from barkeeps-ledger data and post it to Discord.

Steps:
1. Call get_weekly_hourly_trend() to understand daily volume patterns.
2. Call get_weekly_top_pages() to see what content people visited most.
3. Call get_weekly_countries() and get_weekly_cities() for geographic breakdown.
4. Write a 150-250 word narrative and call post_weekly_report(report).

Report format (plain text, no headers, conversational tone):
- Open with total hits and the busiest day
- Highlight 2-3 top pieces of content and what makes them interesting
- Describe the geographic picture: dominant regions, any surprises
- Close with one observation about the overall week (growing/shrinking traffic, pattern shifts, etc.)

Write like a thoughtful person reviewing metrics, not like a dashboard dump.
Example opening: "This week saw 1,240 hits across five sites, peaking on Wednesday.
The biggest draw was metapub.org's gene search tool (312 hits), followed by..."

Avoid: bullet lists, markdown headers, emoji, percentages without context.""",
    max_turns=8,
)


if __name__ == "__main__":
    with AgentRuntime() as runtime:
        result = runtime.run(
            agent,
            "Fetch this week's traffic data and post the weekly narrative report to Discord.",
        )
        if isinstance(result.output, dict):
            print(result.output.get("result", str(result.output)))
        else:
            print(result.output)
