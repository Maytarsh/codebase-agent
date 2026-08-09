"""The agent loop: send, dispatch tool calls, repeat until the model stops asking.

The whole agent is the `run` function at the bottom of this file. Everything above
it exists to keep that function short enough to read in one sitting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.answer import Answer
from agent.client import ModelClient
from agent.schemas import TOOLS_BY_NAME
from agent.tools import ToolError
from agent.usage import Usage

MAX_TURNS = 10


def _tool_result(
    tool_use_id: str, content: str, *, is_error: bool = False
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
    }
    if is_error:
        result["is_error"] = True
    return result


def execute_tool_call(root: Path, block: Any) -> dict[str, Any]:
    """Run one `tool_use` block and return the `tool_result` that answers it.

    Failures the model can recover from come back as results with `is_error`, not
    as exceptions: the model reads the message, adapts, and tries something else.
    A genuine bug in our own code — a schema that disagrees with its function, say
    — still raises, because that is not something the model can fix.
    """
    tool = TOOLS_BY_NAME.get(block.name)
    if tool is None:
        # The registry in schemas.py makes schema/implementation drift impossible,
        # so an unknown name can only be the model inventing one. That is
        # recoverable: tell it what actually exists.
        available = ", ".join(sorted(TOOLS_BY_NAME))
        return _tool_result(
            block.id,
            f"No tool named {block.name!r}. Available tools: {available}.",
            is_error=True,
        )

    try:
        # `root` is bound here, by us. It is absent from every schema precisely so
        # that the model cannot choose it.
        output = tool.run(root, **block.input)
    except ToolError as exc:
        return _tool_result(block.id, str(exc), is_error=True)

    return _tool_result(block.id, output)


def _text_of(response: Any) -> str:
    return "\n".join(
        block.text for block in response.content if block.type == "text"
    ).strip()


@dataclass
class Result:
    """The outcome of one run.

    `answer` is None when the run ended without producing one — either the turn
    cap was hit, or the model stopped for a reason other than finishing. In that
    case `partial_text` holds whatever prose it had emitted, which is usually
    enough to see where it got stuck.
    """

    answer: Answer | None
    turns: int
    usage: Usage
    stopped_early: bool
    partial_text: str = ""
    messages: list[dict[str, Any]] = field(repr=False, default_factory=list)


def run(
    client: ModelClient,
    root: Path,
    question: str,
    *,
    max_turns: int = MAX_TURNS,
) -> Result:
    """Answer `question` about the repository at `root`.

    `client` is injected rather than constructed here, and is only ever asked to
    `send` messages. That argument is the seam: pass a `LiveClient` and this
    talks to the API, pass a `ReplayingClient` and the identical code path runs
    offline against a cassette.
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    usage = Usage()
    last_text = ""

    for turn in range(1, max_turns + 1):
        # A snapshot, not the live list. We keep appending to `messages` after
        # this call returns, and anything that holds on to the request — the
        # recording client, a logger — must not see it change underneath.
        response = client.send(list(messages))
        usage.add(response.usage)

        # Echo the assistant turn back whole. `tool_use` blocks must survive
        # verbatim, and thinking blocks must not be dropped mid-conversation —
        # reconstructing this message from its text alone breaks the next request.
        messages.append({"role": "assistant", "content": response.content})

        text = _text_of(response)
        if text:
            last_text = text

        if response.stop_reason != "tool_use":
            return Result(
                answer=response.parsed_output,
                turns=turn,
                usage=usage,
                stopped_early=False,
                partial_text=last_text,
                messages=messages,
            )

        calls = [block for block in response.content if block.type == "tool_use"]
        results = [execute_tool_call(root, block) for block in calls]

        # Every result for this turn goes back in a single user message. Splitting
        # them across several messages quietly teaches the model to stop making
        # parallel calls — a regression that never shows up as an error.
        messages.append({"role": "user", "content": results})

    return Result(
        answer=None,
        turns=max_turns,
        usage=usage,
        stopped_early=True,
        partial_text=last_text,
        messages=messages,
    )
