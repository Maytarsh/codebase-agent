"""Tests for the harness itself: does replay fail loudly when it should?

A record/replay suite has one characteristic way of rotting. The loop changes,
replay hands back the response recorded for a request nobody is making any more,
and the tests keep passing while testing nothing — the assertions still see a
plausible answer, just not one produced by the code under test.

So the safeguards get their own tests. Each one below is a change that ought to
invalidate a cassette, and each asserts that it is caught rather than absorbed.
"""

from __future__ import annotations

import pytest
from conftest import CASSETTES, FIXTURE_REPO

from agent.client import CassetteError, ReplayingClient
from agent.loop import run

QUESTION = "Which file defines add, and what calls it?"


def test_a_different_question_is_caught(replay):
    """The most likely drift: replaying a cassette against the wrong prompt."""
    with pytest.raises(CassetteError) as caught:
        run(replay("happy_path"), FIXTURE_REPO, "Something else entirely")

    message = str(caught.value)
    assert "turn 1" in message
    assert "messages[0] differs" in message


def test_changed_tool_output_is_caught(replay, tmp_path):
    """Tool results are part of the conversation, so the repo is part of the fixture.

    Point the loop at a different directory and the first tool result diverges,
    which surfaces on turn 2 — the first request that carries it.
    """
    with pytest.raises(CassetteError) as caught:
        run(replay("happy_path"), tmp_path, QUESTION)

    assert "turn 2" in str(caught.value)


def test_a_changed_system_prompt_is_caught(monkeypatch):
    """Config is checked once, when the cassette loads, before any turn runs."""
    monkeypatch.setattr("agent.client.SYSTEM", "You are a helpful assistant.")

    with pytest.raises(CassetteError) as caught:
        ReplayingClient(CASSETTES / "happy_path.json")

    assert "system" in str(caught.value)


def test_a_changed_tool_set_is_caught(monkeypatch):
    """Adding or rewording a tool changes what the model was answering."""
    from agent.schemas import api_schemas

    monkeypatch.setattr(
        "agent.client.api_schemas",
        lambda: api_schemas()[:2],
    )

    with pytest.raises(CassetteError) as caught:
        ReplayingClient(CASSETTES / "happy_path.json")

    assert "tools" in str(caught.value)


def test_running_past_the_end_of_a_cassette_is_caught(replay):
    """Three turns recorded, ten allowed: the loop asks for a fourth."""
    with pytest.raises(CassetteError) as caught:
        run(replay("turn_cap"), FIXTURE_REPO, "What does this repository do?")

    assert "3 turns recorded" in str(caught.value)


def test_replay_needs_no_api_key(replay, monkeypatch):
    """The deliverable: green with the network unplugged and the key unset."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = run(replay("happy_path"), FIXTURE_REPO, QUESTION)

    assert result.answer is not None


def test_every_cassette_is_played_to_the_end(replay):
    """A cassette with unplayed turns left is a fixture nobody finished using."""
    client = replay("happy_path")
    run(client, FIXTURE_REPO, QUESTION)

    assert client.exhausted
