"""The loop's five real failure modes, replayed from cassettes.

Every test here runs the production `run()` against `tests/fixture_repo/` with a
`ReplayingClient` in place of the API. No network, no API key, no cost, and the
same answer every time.

What these prove: dispatch, message shape, error handling, and the turn cap.
What they deliberately do not prove: that the answers are any good. That is a
different job — quality scoring across many samples — and the design brief puts
it out of scope on purpose. These tests are about the loop.
"""

from __future__ import annotations

from conftest import (
    FIXTURE_REPO,
    errors,
    tool_calls,
    tool_results,
    unresolvable_citations,
)

from agent.loop import run

QUESTION = "Which file defines add, and what calls it?"


def test_happy_path(replay):
    """Recorded live, so the assertions split along a line that matters.

    Structural claims are about what *our code* decides — that tool calls get
    dispatched, that nothing errored, that a schema-valid answer came back — and
    those are asserted exactly. Content claims are about what the *model* chose
    to do, and those are asserted loosely, because pinning them would only be
    testing the transcript back to itself.

    That split was invisible while the responses were hand-written. Authoring
    both sides made every assertion look equally solid; re-recording is what
    separated them.
    """
    result = run(replay("happy_path"), FIXTURE_REPO, QUESTION)

    assert not result.stopped_early
    assert result.turns >= 2                     # tool work, then an answer
    assert any(tool_calls(result.messages))      # it used the tools at all
    assert not errors(result.messages)           # and nothing failed

    answer = result.answer
    assert answer is not None
    assert answer.confidence in {"high", "medium"}
    assert "calc.py" in {citation.path for citation in answer.citations}
    assert result.usage.output_tokens > 0

    # Which lines it cites is the model's call; that they resolve is not. A
    # citation pointing at a file or a line that does not exist is fabricated,
    # and fabricated citations are the failure this schema exists to make
    # visible — so this one belongs with the exact assertions, not the loose ones.
    assert unresolvable_citations(answer, FIXTURE_REPO) == []


def test_tool_error_comes_back_as_a_result_and_the_model_recovers(replay):
    """A missing file must not raise out of the loop — the model has to see it."""
    result = run(replay("tool_error"), FIXTURE_REPO, QUESTION)

    failures = errors(result.messages)
    assert len(failures) == 1
    assert "helpers.py" in failures[0]["content"]

    # The recovery is the interesting part: having been told the file does not
    # exist, the next turn reaches for a different tool and then answers.
    assert tool_calls(result.messages) == [["read_file"], ["search"], []]
    assert result.answer is not None
    assert result.answer.citations[0].path == "calc.py"


def test_turn_cap_ends_a_model_that_never_stops(replay):
    """A model that keeps calling tools is a real failure mode, not a hang."""
    result = run(
        replay("turn_cap"),
        FIXTURE_REPO,
        "What does this repository do?",
        max_turns=3,
    )

    assert result.stopped_early
    assert result.turns == 3
    # No final turn means no schema-validated answer. Saying so is the point:
    # the caller must be able to tell "gave up" from "answered".
    assert result.answer is None


def test_path_outside_the_root_is_refused(replay):
    """The model supplies the path, so the path is untrusted input."""
    result = run(
        replay("path_traversal"),
        FIXTURE_REPO,
        "What is in the system password file?",
    )

    failures = errors(result.messages)
    assert len(failures) == 1
    assert "outside the repository root" in failures[0]["content"]
    # Refused, not read: nothing that looks like /etc/passwd reached the model.
    assert "root:" not in failures[0]["content"]

    # And the refusal is a tool result, not an exception — the run completes.
    assert result.answer is not None
    assert result.answer.confidence == "low"


def test_parallel_tool_calls_return_in_a_single_message(replay):
    """Two calls in one assistant turn, two results in one user message.

    Splitting them across two messages still works, which is what makes this
    worth asserting: the model quietly stops making parallel calls and nothing
    ever errors.
    """
    result = run(
        replay("parallel_calls"),
        FIXTURE_REPO,
        "What do calc.py and main.py contain?",
    )

    assert tool_calls(result.messages) == [["read_file", "read_file"], []]

    groups = tool_results(result.messages)
    assert len(groups) == 1
    assert len(groups[0]) == 2

    # Every tool_use needs its own tool_result; a missing one is a 400 next turn.
    requested = [
        block.id
        for message in result.messages
        if message["role"] == "assistant"
        for block in message["content"]
        if block.type == "tool_use"
    ]
    assert [result["tool_use_id"] for result in groups[0]] == requested


def test_thinking_blocks_are_echoed_back_untouched(replay):
    """The loop appends `response.content` whole, and thinking is part of it.

    Mostly this test is free: the cassette's second request contains the first
    turn's thinking block, so dropping it makes the replay safeguard fire before
    this assertion is ever reached. The assertion is here to name the rule.
    """
    result = run(replay("tool_error"), FIXTURE_REPO, QUESTION)

    first = next(m for m in result.messages if m["role"] == "assistant")
    assert [block.type for block in first["content"]] == ["thinking", "tool_use"]
