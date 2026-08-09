"""Regenerate the cassettes the test suite replays.

    uv run python tests/make_cassettes.py

These five cassettes are not recorded from the live API. The model responses in
this file are written by hand and fed through `RecordingClient` exactly as live
ones would be — `RecordingClient` does not care what its inner client is, so a
scripted stand-in produces a cassette indistinguishable from a real recording.

That is deliberate, and it is the point of the format. Three of the five
scenarios are ones the live API would rarely or never produce on demand: a model
that keeps calling tools until the cap, a model that asks for `/etc/passwd`, a
model that emits two tool calls in one turn. Once responses are data on disk,
those stop being lucky recordings and become fixtures you author.

The tool *results* in each cassette are real: the loop runs the actual tools
against `tests/fixture_repo/` while this script records. So the cassettes still
prove the dispatch path works — only the model's side is invented.

Re-run this after changing the system prompt, the tool schemas, the answer
schema, or the fixture repository. Replay checks all of those and will refuse a
stale cassette rather than quietly replay it.
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


# --- the five scenarios -----------------------------------------------------

QUESTION = "Which file defines add, and what calls it?"

SCENARIOS: dict[str, dict[str, Any]] = {
    # 1. Happy path: search, then read, then answer.
    "happy_path": {
        "question": QUESTION,
        "responses": [
            turn(
                text("Searching for the definition first."),
                tool_use("toolu_01", "search", pattern=r"def add"),
            ),
            turn(tool_use("toolu_02", "search", pattern=r"\badd\(", glob="**/*.py")),
            turn(
                final(
                    "add is defined in calc.py and is called once, from main.py. "
                    "main.py imports it from calc and prints add(2, 3).",
                    [
                        ("calc.py", 4, "def add(left, right) — the definition."),
                        ("main.py", 3, "main.py imports add from calc."),
                        ("main.py", 7, "The only call site: print(add(2, 3))."),
                    ],
                    "high",
                ),
                output_tokens=210,
            ),
        ],
    },
    # 2. Tool error recovery: a file that does not exist, then a different plan.
    "tool_error": {
        "question": QUESTION,
        "responses": [
            turn(tool_use("toolu_01", "read_file", path="helpers.py")),
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
    # 3. Turn cap: a model that never stops calling tools. Recorded at three
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
    # 4. Path traversal: the model asks for a file outside the root.
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
    # 5. Parallel tool calls: two tool_use blocks in a single assistant turn.
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
