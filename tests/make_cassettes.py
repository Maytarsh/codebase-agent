"""Regenerate the four hand-authored cassettes the test suite replays.

    uv run python tests/make_cassettes.py

**This script does not touch happy_path.json.** That one is recorded against the
live API and has to be re-made with the CLI:

    uv run python -m agent --repo tests/fixture_repo \\
      --record tests/cassettes/happy_path.json \\
      "Which file defines add, and what calls it?"

The four here are authored rather than recorded, because the API will not
produce them on demand: a model that keeps calling tools until the turn cap, one
that asks for `/etc/passwd`, one that emits two tool calls in a single turn, one
that asks for a file that is not there. The responses below are written by hand
and fed through `RecordingClient` exactly as live ones would be —
`RecordingClient` does not care what its inner client is, so a scripted stand-in
produces a cassette indistinguishable in format from a real recording.

Indistinguishable in format, not in truth, which is why the split exists. An
authored response encodes what its author believes the API returns, and a wrong
belief yields a suite that is green against a fiction. The first draft of
happy_path had the model searching serially, one tool call per turn; the live
recording that replaced it calls two tools in parallel on both turns. Keep at
least one cassette that reality wrote.

The tool *results* in every cassette are real either way: the loop runs the
actual tools against `tests/fixture_repo/` while recording.

Re-run this after changing the system prompt, the tool schemas, the answer
schema, or the fixture repository — and re-record happy_path too, since replay
checks all of those and will refuse a stale cassette rather than quietly replay
it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agent.client import MODEL, RecordingClient, Response
from agent.loop import run

HERE = Path(__file__).parent
CASSETTES = HERE / "cassettes"
FIXTURE_REPO = HERE / "fixture_repo"


class ScriptedClient:
    """Returns pre-built responses in order. Stands in for the live API."""

    def __init__(self, responses: list[Response]) -> None:
        self._responses = responses
        self._index = 0

    def send(self, messages: Any) -> Response:
        response = self._responses[self._index]
        self._index += 1
        return response


def turn(*blocks: dict[str, Any], output_tokens: int = 120) -> Response:
    """One assistant response, in the shape the SDK hands back."""
    has_tool_use = any(block["type"] == "tool_use" for block in blocks)
    # Derived from the content, not from hash() — string hashing is salted per
    # process, so ids would change on every regeneration and every cassette
    # would show up in the diff whether or not anything meaningful moved.
    digest = hashlib.sha256(json.dumps(blocks, sort_keys=True).encode()).hexdigest()
    return Response.model_validate(
        {
            "id": f"msg_fixture_{digest[:12]}",
            "type": "message",
            "role": "assistant",
            "model": MODEL,
            "stop_reason": "tool_use" if has_tool_use else "end_turn",
            "stop_sequence": None,
            # Invented but plausible, so that a replayed run still prints a
            # sensible-looking cost. Nothing asserts on the exact numbers.
            "usage": {"input_tokens": 1500, "output_tokens": output_tokens},
            "content": list(blocks),
        }
    )


def text(body: str) -> dict[str, Any]:
    return {"type": "text", "text": body}


def thinking(body: str) -> dict[str, Any]:
    """A thinking block, which every real response carries and none of these did.

    Real ones come back with an empty `thinking` and a 352-character signature —
    see happy_path.json. The prose here is for whoever reads this file; the
    signature is the part that has to survive the round trip, and it is fake.
    Which is the argument for keeping one recorded cassette in the set.
    """
    return {"type": "thinking", "thinking": body, "signature": "fixture-signature"}


def tool_use(call_id: str, name: str, **arguments: Any) -> dict[str, Any]:
    return {"type": "tool_use", "id": call_id, "name": name, "input": arguments}


def final(answer: str, citations: list[tuple[str, int, str]], confidence: str):
    """The final turn: a text block whose text is JSON and whose parse succeeded."""
    payload = {
        "answer": answer,
        "citations": [
            {"path": path, "line": line, "detail": detail}
            for path, line, detail in citations
        ],
        "confidence": confidence,
    }
    return {
        "type": "text",
        "text": json.dumps(payload),
        "parsed_output": payload,
    }


# --- the four authored scenarios --------------------------------------------
#
# The happy path is deliberately absent. It is recorded live; see the module
# docstring for the command. Adding it back here would overwrite that recording
# with a guess, and every test would still pass.

QUESTION = "Which file defines add, and what calls it?"

SCENARIOS: dict[str, dict[str, Any]] = {
    # 1. Tool error recovery: a file that does not exist, then a different plan.
    "tool_error": {
        "question": QUESTION,
        "responses": [
            turn(
                thinking("Helpers usually live in helpers.py. I'll try reading it."),
                tool_use("toolu_01", "read_file", path="helpers.py"),
            ),
            turn(
                text("That file does not exist; searching instead."),
                tool_use("toolu_02", "search", pattern=r"def add"),
            ),
            turn(
                final(
                    "add is defined in calc.py.",
                    [("calc.py", 4, "def add(left, right).")],
                    "high",
                ),
                output_tokens=90,
            ),
        ],
    },
    # 2. Turn cap: a model that never stops calling tools. Recorded at three
    #    turns and replayed with max_turns=3, so the cap is what ends the run.
    "turn_cap": {
        "question": "What does this repository do?",
        "max_turns": 3,
        "responses": [
            turn(tool_use("toolu_01", "list_files", pattern="**/*.py")),
            turn(tool_use("toolu_02", "list_files", pattern="**/*.md")),
            turn(tool_use("toolu_03", "list_files", pattern="**/*")),
        ],
    },
    # 3. Path traversal: the model asks for a file outside the root.
    "path_traversal": {
        "question": "What is in the system password file?",
        "responses": [
            turn(tool_use("toolu_01", "read_file", path="../../../../etc/passwd")),
            turn(
                final(
                    "That file is outside this repository, so I cannot read it.",
                    [],
                    "low",
                ),
                output_tokens=60,
            ),
        ],
    },
    # 4. Parallel tool calls: two tool_use blocks in a single assistant turn.
    "parallel_calls": {
        "question": "What do calc.py and main.py contain?",
        "responses": [
            turn(
                tool_use("toolu_01", "read_file", path="calc.py"),
                tool_use("toolu_02", "read_file", path="main.py"),
            ),
            turn(
                final(
                    "calc.py defines add and divide; main.py calls both and prints "
                    "the results.",
                    [
                        ("calc.py", 4, "def add(left, right)."),
                        ("main.py", 6, "def main() calls add and divide."),
                    ],
                    "high",
                ),
                output_tokens=150,
            ),
        ],
    },
}


def main() -> None:
    for name, scenario in SCENARIOS.items():
        path = CASSETTES / f"{name}.json"
        client = RecordingClient(ScriptedClient(scenario["responses"]), path)
        result = run(
            client,
            FIXTURE_REPO,
            scenario["question"],
            max_turns=scenario.get("max_turns", 10),
        )
        print(f"{path.name:<24} {result.turns} turns, answer={result.answer is not None}")


if __name__ == "__main__":
    main()
