# agentspan-examples

Example agent workflows built with [agentspan](https://conductor.ai) and the Conductor OSS Python SDK.

## Setup

```bash
cp .env.example .env
# fill in ANTHROPIC_API_KEY and AGENTSPAN_SERVER_URL
```

You need a running Conductor server. For local dev, build and start `conductor-server` from [conductor-oss/conductor](https://github.com/conductor-oss/conductor) main:

```bash
./gradlew :conductor-server:bootJar
java -jar server/build/libs/conductor-server-*-boot.jar --server.port=7001
```

Install the Python SDK:

```bash
pip install conductor-python
```

## Examples

### `games/number_guesser.py`

A single agent finds a secret number 1–100 using binary search. The tool maintains
state across calls (via `ToolContext`) so the secret persists between guesses.

```bash
python games/number_guesser.py
```

### `games/adversarial_number_game.py`

Two agents compete in a number-guessing game:

- **Keeper** picks a secret number 1–100 and can lie *once* (flip higher↔lower) to slow the guesser down
- **Guesser** uses binary search but must detect the lie by spotting contradictions in the response history

```bash
python games/adversarial_number_game.py
```

Override the model via env var (default: `anthropic/claude-haiku-4-5-20251001`):

```bash
AGENTSPAN_LLM_MODEL=ollama/qwen3:8b python games/adversarial_number_game.py
```

## barkeeps-ledger workflows

Three agents that query a live web analytics API and post intelligence to Discord.
See [`barkeeps/README.md`](barkeeps/README.md) for setup and scheduling.

### `barkeeps/hourly_digest.py`

Fetches the last hour of traffic (top pages, countries, trend) and posts a 3-5 sentence
summary to Discord. Run hourly via cron.

### `barkeeps/anomaly_detector.py`

Compares current-hour traffic against the 6-hour rolling average. Posts a Discord alert
on spikes (≥ 2×) or drops (≤ 0.3×); silent when traffic is normal. Run every 15 minutes.

### `barkeeps/weekly_report.py`

Synthesizes 7 days of hourly data, top pages, and visitor geography into a 150-250 word
narrative posted to Discord. Run weekly.
