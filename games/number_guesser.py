#!/usr/bin/env python3
"""Single-agent number guessing game using agentspan.

The agent uses binary search to find a secret number 1-100,
calling a tool that maintains state across guesses.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    export AGENTSPAN_SERVER_URL=http://localhost:7001/api
    python games/number_guesser.py
"""

import os
import random
from conductor.ai.agents import Agent, AgentRuntime, ToolContext, tool

MODEL = os.environ.get("AGENTSPAN_LLM_MODEL", "anthropic/claude-haiku-4-5-20251001")


@tool(stateful=True)
def check_guess(guess: int, context: ToolContext) -> str:
    """Check a guess against the secret number. Returns 'higher', 'lower', or 'correct'."""
    secret_number = context.state.get("secret")

    if secret_number is None:
        secret_number = random.randint(1, 100)
        context.state["secret"] = secret_number

    if guess < secret_number:
        return "higher"
    elif guess > secret_number:
        return "lower"
    else:
        return "correct"


agent = Agent(
    name="number_guesser",
    model=MODEL,
    tools=[check_guess],
    instructions=(
        "A random number from 1-100 has been selected. "
        "Find it using the check_guess tool. "
        "Use binary search to minimise the number of guesses."
    ),
    stateful=True,
    max_turns=20,
)


if __name__ == "__main__":
    with AgentRuntime() as runtime:
        result = runtime.run(agent, "Please find the secret number.")
        result.print_result()
