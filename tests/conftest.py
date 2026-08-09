"""Shared helpers. Nothing here touches the network or needs an API key."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent.client import ReplayingClient

HERE = Path(__file__).parent
CASSETTES = HERE / "cassettes"
FIXTURE_REPO = HERE / "fixture_repo"


@pytest.fixture
def replay():
    """Build a client that answers from the named cassette."""

    def build(name: str) -> ReplayingClient:
        return ReplayingClient(CASSETTES / f"{name}.json")

    return build


def tool_calls(messages: list[dict[str, Any]]) -> list[list[str]]:
    """The tool names requested in each assistant turn, in order.

    Assistant content is echoed back as the SDK objects it arrived as, so these
    are attribute lookups rather than dict keys — a small asymmetry with the
    tool results below, and a deliberate one: those blocks must survive verbatim.
    """
    return [
        [block.name for block in message["content"] if block.type == "tool_use"]
        for message in messages
        if message["role"] == "assistant"
    ]


def tool_results(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """The tool results in each user turn, grouped by the message they arrived in.

    Grouping matters: several results belonging to one assistant turn must come
    back in a single message, so the shape of this list is itself under test.
    """
    return [
        message["content"]
        for message in messages
        if message["role"] == "user" and isinstance(message["content"], list)
    ]


def unresolvable_citations(answer: Any, root: Path) -> list[str]:
    """Citations that do not point at a real line of a real file under `root`.

    Deliberately not an opinion about *which* lines the model should have cited —
    that is a model decision, and pinning it would make the test a transcript of
    one recording. Whether a citation resolves at all is not a decision: a path
    that does not exist, or a line past the end of the file, is wrong no matter
    what the prose around it says.

    This is the claim the whole project rests on. An answer whose citations do
    not resolve is not a worse answer, it is a fabricated one.
    """
    problems = []
    for citation in answer.citations:
        path = (root / citation.path).resolve()
        if not path.is_relative_to(root.resolve()):
            problems.append(f"{citation.path}:{citation.line} — outside the root")
            continue
        if not path.is_file():
            problems.append(f"{citation.path}:{citation.line} — no such file")
            continue
        length = len(path.read_text().splitlines())
        if not 1 <= citation.line <= length:
            problems.append(
                f"{citation.path}:{citation.line} — file has {length} lines"
            )
    return problems


def errors(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every tool result that came back flagged as an error."""
    return [
        result
        for group in tool_results(messages)
        for result in group
        if result.get("is_error")
    ]
