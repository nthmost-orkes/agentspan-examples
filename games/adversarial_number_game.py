#!/usr/bin/env python3
"""Adversarial 2-player number guessing game using agentspan.

Two agents compete:
  Keeper  — picks a secret number 1-100, responds to guesses, can lie ONCE
              (flip 'higher' <-> 'lower'). Goal: maximise turns before guesser wins.
  Guesser — binary-searches, but knows the keeper can lie once.
              Must detect contradictions and recalculate.

Shared state is a JSON file — necessary because agentspan tool workers run in
a separate OS process from the main loop.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    export AGENTSPAN_SERVER_URL=http://localhost:7001/api
    python games/adversarial_number_game.py
"""

import json
import os
import tempfile
from conductor.ai.agents import Agent, AgentRuntime, tool

GAME_FILE = os.path.join(tempfile.gettempdir(), "agentspan_number_game.json")
MAX_TURNS = 20
MODEL = os.environ.get("AGENTSPAN_LLM_MODEL", "anthropic/claude-haiku-4-5-20251001")


# ── Shared state helpers ───────────────────────────────────────────────

def _load() -> dict:
    with open(GAME_FILE) as f:
        return json.load(f)

def _save(state: dict) -> None:
    with open(GAME_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Keeper tools ───────────────────────────────────────────────────────

@tool
def set_secret(n: int) -> str:
    """Choose and lock in the secret number (1-100). Call exactly once at game start."""
    if not (1 <= n <= 100):
        return "error: n must be 1-100"
    state = _load()
    if state.get("secret") is not None:
        return "error: already set"
    state["secret"] = n
    _save(state)
    return f"Secret {n} locked in."


@tool
def respond_to_guess(guess: int, use_lie: bool) -> str:
    """Respond to the guesser's guess. Returns what you told them.

    use_lie=True flips the real direction (higher->lower or lower->higher).
    You may only lie ONCE. Cannot lie on a correct guess.
    """
    state = _load()
    secret = state.get("secret")
    if secret is None:
        return "error: secret not set"

    if guess == secret:
        truth = "correct"
    elif guess < secret:
        truth = "higher"
    else:
        truth = "lower"

    if use_lie and not state.get("lie_used", False) and truth != "correct":
        state["lie_used"] = True
        told = "lower" if truth == "higher" else "higher"
        was_lie = True
    else:
        told = truth
        was_lie = False

    state.setdefault("history", []).append({
        "turn": len(state["history"]) + 1,
        "guess": guess,
        "told": told,
        "was_lie": was_lie,
    })
    if truth == "correct":
        state["solved"] = True

    _save(state)
    return told


@tool
def keeper_get_history() -> str:
    """[KEEPER] Get full history including which turns were lies."""
    state = _load()
    history = state.get("history", [])
    return json.dumps(history, indent=2) if history else "No guesses yet."


# ── Guesser tools ──────────────────────────────────────────────────────

@tool
def submit_guess(n: int) -> str:
    """Submit your next guess (1-100). Returns 'ok' — keeper responds next turn."""
    if not (1 <= n <= 100):
        return "error: must be 1-100"
    state = _load()
    state["pending_guess"] = n
    _save(state)
    return "ok"


@tool
def guesser_get_history() -> str:
    """[GUESSER] Get the history of guesses and keeper responses.
    Note: the keeper may have lied on one turn — you must deduce which."""
    state = _load()
    history = [
        {"turn": h["turn"], "guess": h["guess"], "told": h["told"]}
        for h in state.get("history", [])
    ]
    return json.dumps(history, indent=2) if history else "No guesses yet."


# ── Agents ─────────────────────────────────────────────────────────────

keeper = Agent(
    name="keeper_agent",
    model=MODEL,
    tools=[set_secret, respond_to_guess, keeper_get_history],
    instructions="""You are the Keeper in an adversarial number-guessing game.

GOAL: Make the Guesser take as many turns as possible to find your secret number.

RULES:
- At game start, call set_secret(n). Avoid round numbers — pick something like 73 or 41.
- Each turn you are given the guesser's guess. Call respond_to_guess(guess, use_lie).
- use_lie=True flips your response (higher<->lower). You may only do this ONCE.
- You CANNOT lie when the guess is exactly correct.

LIE STRATEGY: The most damaging lie happens when the guesser has narrowed to a
small range [a,b] and picks the midpoint m. Lying then pushes them into the wrong
half, wasting the most turns. Save it for that moment.

After each turn briefly explain your strategic reasoning.""",
    max_turns=5,
)

guesser = Agent(
    name="guesser_agent",
    model=MODEL,
    tools=[submit_guess, guesser_get_history],
    instructions="""You are the Guesser in an adversarial number-guessing game.
The keeper has chosen a number from 1-100. Find it.

STRATEGY:
- Use binary search as your base: maintain a current range [lo, hi].
- The keeper can lie ONCE — they will flip one 'higher' to 'lower' or vice versa.

DETECTING THE LIE:
Before each guess, review the full history for a logical contradiction:
  e.g. told 'higher' on guess 50, then later told 'lower' on guess 45
  -> impossible if both were honest (45 < 50, so 45 can't be "lower" than 50 was "higher").
When you find one, exactly one of those two responses was the lie. Reason through
which is more likely, ignore it, and recalculate your range.

Call guesser_get_history() first, then submit_guess(n).
After submitting, state: your current range, whether you've detected a lie, and why you picked that number.""",
    max_turns=8,
)


# ── Display helpers ────────────────────────────────────────────────────

def _text(result) -> str:
    """Extract plain text from an AgentResult (output is a dict with 'result' key)."""
    if isinstance(result.output, dict):
        return result.output.get("result", str(result.output))
    return str(result.output)

def divider(label: str = "") -> None:
    if label:
        print(f"\n-- {label} " + "-" * max(0, 44 - len(label)))
    else:
        print("-" * 50)


# ── Game loop ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    _save({"secret": None, "lie_used": False, "history": [], "solved": False})

    print("=" * 50)
    print("  ADVERSARIAL NUMBER GAME")
    print("  Keeper vs Guesser  |  1-100  |  One lie allowed")
    print("=" * 50)

    with AgentRuntime() as runtime:

        # Phase 1: Keeper picks the secret
        divider("KEEPER SETS SECRET")
        result = runtime.run(
            keeper,
            "Choose your secret number. Call set_secret(n) — pick strategically.",
        )
        print(_text(result))

        state = _load()
        print(f"\n[meta] Secret locked: {state['secret']}")

        # Phase 2: Alternating turns
        turn = 0
        while not state.get("solved") and turn < MAX_TURNS:
            turn += 1
            divider(f"TURN {turn}")

            # Guesser's move — sees history without lie metadata
            guesser_history = [
                {"turn": h["turn"], "guess": h["guess"], "told": h["told"]}
                for h in state.get("history", [])
            ]
            guesser_prompt = (
                f"Turn {turn}. History so far (keeper may have lied on one turn):\n"
                + json.dumps(guesser_history, indent=2)
                + "\n\nCheck for contradictions, then call submit_guess(n)."
            )
            print("[GUESSER]")
            result = runtime.run(guesser, guesser_prompt)
            print(_text(result))

            state = _load()
            guess = state.get("pending_guess")
            if guess is None:
                print("[meta] Guesser didn't submit — aborting.")
                break

            # Keeper's move
            lie_status = "already used" if state.get("lie_used") else "still available"
            keeper_prompt = (
                f"Guesser guessed {guess}. Your lie is {lie_status}.\n"
                f"Call respond_to_guess({guess}, use_lie=True/False).\n"
                "Explain your strategic choice."
            )
            print("[KEEPER]")
            result = runtime.run(keeper, keeper_prompt)
            print(_text(result))

            state = _load()
            if state.get("history"):
                last = state["history"][-1]
                lie_tag = "  <- LIE" if last["was_lie"] else ""
                print(f"\n[meta] Keeper told guesser: '{last['told']}'{lie_tag}")

        # Results
        state = _load()
        divider("GAME OVER")
        print(f"Secret number : {state['secret']}")
        print(f"Total turns   : {len(state['history'])}")
        lie_turn = next((h["turn"] for h in state["history"] if h["was_lie"]), None)
        print(f"Lie used      : {'turn ' + str(lie_turn) if lie_turn else 'never'}")
        print(f"Guesser won   : {'yes' if state.get('solved') else 'no (ran out of turns)'}")
        print()
        print("Full history (truth revealed):")
        for h in state["history"]:
            lie_tag = "  <- LIE" if h["was_lie"] else ""
            print(f"  Turn {h['turn']:2d}  guess={h['guess']:3d}  told='{h['told']}'{lie_tag}")

    if os.path.exists(GAME_FILE):
        os.remove(GAME_FILE)
