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


def errors(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every tool result that came back flagged as an error."""
    return [
        result
        for group in tool_results(messages)
        for result in group
        if result.get("is_error")
    ]
