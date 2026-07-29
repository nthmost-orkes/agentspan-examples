#!/usr/bin/env python3
"""Traffic anomaly detector for barkeeps-ledger, alerts posted to Discord.

The agent compares the current hour's traffic against the recent baseline
and posts an alert if a spike or drop is detected.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    export AGENTSPAN_SERVER_URL=http://localhost:7001/api
    export DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
    python barkeeps/anomaly_detector.py

Schedule every 15 minutes with cron:
    */15 * * * * cd /path/to/agentspan-examples && python barkeeps/anomaly_detector.py
"""

import os
import time
import requests
from conductor.ai.agents import Agent, AgentRuntime, tool

MODEL = os.environ.get("AGENTSPAN_LLM_MODEL", "anthropic/claude-haiku-4-5-20251001")
BARKEEPS_BASE = os.environ.get("BARKEEPS_BASE_URL", "https://bar.nthmost.net")
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]


@tool
def get_hourly_data() -> str:
    """Fetch the last 24 hours of traffic broken down by hour.

    Returns a JSON-like table with hour (Unix timestamp), hits, and a note
    marking the current hour and computing the 6-hour rolling average.
    """
    r = requests.get(f"{BARKEEPS_BASE}/api/hourly", timeout=10)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return "No hourly data available."

    now = int(time.time())
    current_hour_start = (now // 3600) * 3600
    recent = [row for row in rows if row["hour"] >= now - 86400]
    if not recent:
        recent = rows[-24:]

    lines = ["hour_utc            hits  label"]
    baseline_hits = [row["hits"] for row in recent if row["hour"] < current_hour_start]
    baseline_6h = [row["hits"] for row in recent if current_hour_start - 21600 <= row["hour"] < current_hour_start]
    avg_6h = sum(baseline_6h) / len(baseline_6h) if baseline_6h else 0

    for row in recent:
        ts = time.strftime("%Y-%m-%d %H:00", time.gmtime(row["hour"]))
        label = ""
        if row["hour"] == current_hour_start:
            label = "<-- current hour"
        lines.append(f"{ts}  {row['hits']:4d}  {label}")

    lines.append(f"\n6-hour baseline average: {avg_6h:.1f} hits/hour")
    current = next((row["hits"] for row in recent if row["hour"] == current_hour_start), 0)
    lines.append(f"Current hour so far:     {current} hits")
    if avg_6h > 0:
        ratio = current / avg_6h
        lines.append(f"Ratio (current/avg):     {ratio:.2f}x")
    return "\n".join(lines)


@tool
def get_top_pages_now(window_seconds: int = 3600) -> str:
    """Fetch the top pages driving traffic right now (last window_seconds)."""
    r = requests.get(f"{BARKEEPS_BASE}/api/rankings", params={"window": window_seconds}, timeout=10)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return "No rankings data."
    lines = [f"{row['hits']:4d}  {row['site']}{row['url']}" for row in rows[:10]]
    return "\n".join(lines)


@tool
def get_recent_hits(n: int = 30) -> str:
    """Fetch the N most recent hits to inspect what's coming in right now."""
    r = requests.get(f"{BARKEEPS_BASE}/api/recent", params={"n": n}, timeout=10)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return "No recent hits."
    lines = []
    for row in rows[:n]:
        ts = time.strftime("%H:%M:%S", time.localtime(row["ts"]))
        lines.append(f"{ts}  {row['site']}{row['url']}  [{row['cc']}/{row['city']}]  ref={row.get('referer','?')}")
    return "\n".join(lines)


@tool
def post_anomaly_alert(message: str, severity: str) -> str:
    """Post an anomaly alert to Discord.

    severity: 'spike' | 'drop' | 'none'
    Only posts if severity is 'spike' or 'drop'. Returns 'skipped' if none.
    """
    if severity == "none":
        return "skipped — no anomaly detected"
    label = {"spike": "TRAFFIC SPIKE", "drop": "TRAFFIC DROP"}.get(severity, "ANOMALY")
    payload = {
        "content": f"**[barkeeps {label}]** {message}",
        "username": "barkeeps-ledger",
    }
    r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    r.raise_for_status()
    return "alert sent"


agent = Agent(
    name="barkeeps_anomaly_detector",
    model=MODEL,
    tools=[get_hourly_data, get_top_pages_now, get_recent_hits, post_anomaly_alert],
    instructions="""You detect traffic anomalies in barkeeps-ledger data and alert on Discord.

Steps:
1. Call get_hourly_data() to see the current hour vs the 6-hour baseline.
2. If the ratio is > 2.0 (spike) or < 0.3 (drop), investigate further:
   - Call get_top_pages_now(3600) to see what's being hit
   - Call get_recent_hits(30) to see the pattern
3. Call post_anomaly_alert(message, severity) where:
   - severity is 'spike', 'drop', or 'none'
   - message (1-2 sentences) explains: what the ratio is, which pages/sites are involved,
     and the geographic source if notable

Anomaly thresholds:
- Spike: current hour ≥ 2× the 6-hour average
- Drop: current hour ≤ 0.3× the 6-hour average (and average > 5 hits to avoid noise)
- None: everything looks normal — call post_anomaly_alert with severity='none'

Be matter-of-fact. "nthmost.com seeing 3.2× normal traffic, top hit: /blog/post-x (47 hits),
most visitors from DE." is a good alert. No emoji, no drama.""",
    max_turns=8,
)


if __name__ == "__main__":
    with AgentRuntime() as runtime:
        result = runtime.run(
            agent,
            "Check for traffic anomalies in the last hour and alert Discord if needed.",
        )
        if isinstance(result.output, dict):
            print(result.output.get("result", str(result.output)))
        else:
            print(result.output)
