"""The seam between the loop and the network.

The loop knows one method: `send(messages) -> response`. It does not know the
SDK exists. Three implementations sit behind that method:

    Live       calls the real API
    Recording  delegates to another client, writes each exchange to a cassette
    Replaying  reads the next response from a cassette, never touches the network

That is what makes the tests possible. An agent's output is different every run,
so there is no stable string to assert on; once responses are files on disk the
whole thing is deterministic, free, and works with the network unplugged.

**Where the seam sits, and what that costs.** This interface is above HTTP, so
the tests cover the loop — dispatch, ordering, error handling, the turn cap —
but *not* request construction or serialization. If `api_schemas()` started
emitting a malformed schema, replay would not notice. Intercepting at the HTTP
transport instead, which is what VCR.py and pytest-recording do, would cover
both, at the price of coupling the tests to httpx internals. For a first build
the higher seam is the better trade; the point is knowing which coverage you
gave up.

**Cassettes are reviewable artifacts.** No credentials pass through this layer —
the API key lives in the HTTP headers, which are a layer below — so there is
nothing to redact here. But a cassette does contain the system prompt, the
question, and the contents of every file the tools read. Record against a
repository you would be happy to commit.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from anthropic.types import ParsedMessage

from agent.answer import Answer
from agent.schemas import api_schemas

MODEL = "claude-opus-5"
MAX_TOKENS = 4096

SYSTEM = (
    "You answer questions about a code repository by calling the tools provided.\n\n"
    "Work only from evidence you find in the repository, never from prior knowledge "
    "about similarly-named projects. Search before you read: searching is far cheaper "
    "than opening files one at a time. When you have the answer, return it in the "
    "required structure, citing every file and line you actually read."
)

CASSETTE_VERSION = 1

# The response type the loop works with, whichever client produced it. Replay
# reconstructs one of these from JSON, so a replayed turn is indistinguishable
# from a live one as far as the loop is concerned.
Response = ParsedMessage[Answer]

Messages = Sequence[Mapping[str, Any]]


class ModelClient(Protocol):
    """One request, one response. The entire surface the loop depends on."""

    def send(self, messages: Messages) -> Response: ...


def request_config() -> dict[str, Any]:
    """Everything about a request that does not change from turn to turn.

    Stored once per cassette rather than on every interaction. Replay checks it,
    so changing the system prompt or the tool schemas fails loudly instead of
    quietly replaying answers to a question that is no longer being asked.
    """
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM,
        "tools": api_schemas(),
        "output_schema": Answer.model_json_schema(),
    }


def _jsonable(value: Any) -> Any:
    """Round-trip through JSON so SDK content blocks become plain data.

    Assistant turns are echoed back to the API as the SDK objects that came out
    of it, so `messages` is a mix of dicts and pydantic models. Cassettes hold
    only the former, and comparing plain data avoids depending on how the SDK
    happens to implement equality.
    """
    return json.loads(json.dumps(value, default=_encode))


def _encode(obj: Any) -> Any:
    dump = getattr(obj, "model_dump", None)
    if dump is not None:
        return dump(mode="json")
    raise TypeError(f"cannot serialize {type(obj).__name__} into a cassette")


class LiveClient:
    """Calls the real API. The only class in this project that imports the SDK."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def send(self, messages: Messages) -> Response:
        # parse() is create() plus schema enforcement: the API is told the final
        # answer must match Answer's schema, and the SDK hands back a validated
        # instance on `parsed_output`. On turns that end in a tool call there is
        # no final answer yet, so `parsed_output` is None.
        return self._client.messages.parse(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            tools=api_schemas(),
            output_format=Answer,
            messages=list(messages),
        )


class RecordingClient:
    """Delegates to another client and writes every exchange to a cassette.

    `inner` is usually a `LiveClient`, but nothing here requires it. The cassette
    fixtures in the test suite are produced by pointing this at a scripted client
    that returns hand-authored responses — which is how scenarios the live API
    would rarely produce, like a model that never stops calling tools, become
    recordings like any other.
    """

    def __init__(self, inner: ModelClient, path: Path) -> None:
        self._inner = inner
        self._path = path
        self._interactions: list[dict[str, Any]] = []

    def send(self, messages: Messages) -> Response:
        sent = _jsonable(messages)
        response = self._inner.send(messages)
        self._interactions.append(
            {
                "messages": sent,
                "response": json.loads(response.model_dump_json()),
            }
        )
        # Written after every turn, not at the end, so a run that crashes on turn
        # three still leaves the two turns that led up to it on disk.
        self._write()
        return response

    def _write(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "version": CASSETTE_VERSION,
            "config": request_config(),
            "interactions": self._interactions,
        }
        self._path.write_text(json.dumps(document, indent=2) + "\n")


class CassetteError(AssertionError):
    """Replay could not honour a request. Always a bug in the test or the loop."""


class ReplayingClient:
    """Serves recorded responses in order. Never touches the network.

    Ordered playback rather than request hashing: hashing survives loop changes
    better, but needs canonically serialized requests to be correct and is easy
    to get subtly wrong. The safeguard below buys most of what hashing would.
    """

    def __init__(self, path: Path) -> None:
        document = json.loads(path.read_text())
        self._path = path
        self._interactions = document["interactions"]
        self._index = 0

        recorded = document["config"]
        current = request_config()
        if recorded != current:
            raise CassetteError(
                f"{path.name} was recorded with a different request configuration "
                f"({_describe_config_drift(recorded, current)}). Re-record it."
            )

    def send(self, messages: Messages) -> Response:
        if self._index >= len(self._interactions):
            raise CassetteError(
                f"{self._path.name} has {len(self._interactions)} turns recorded "
                f"and the loop asked for another. Either the loop no longer stops "
                f"where it did, or the cassette is truncated."
            )

        interaction = self._interactions[self._index]
        sent = _jsonable(messages)

        # The safeguard. Without it, a change to the loop replays the wrong
        # response and the test passes while testing nothing — it would still
        # see a plausible answer come back, just not one that answers what was
        # asked. With it, divergence names the turn that drifted.
        if interaction["messages"] != sent:
            raise CassetteError(
                f"{self._path.name} turn {self._index + 1}: the loop sent a "
                f"different request than was recorded.\n"
                f"{_describe_message_drift(interaction['messages'], sent)}"
            )

        self._index += 1
        return Response.model_validate(interaction["response"])

    @property
    def exhausted(self) -> bool:
        """True once every recorded turn has been played."""
        return self._index >= len(self._interactions)


def _describe_config_drift(
    recorded: Mapping[str, Any], current: Mapping[str, Any]
) -> str:
    differing = sorted(
        key
        for key in set(recorded) | set(current)
        if recorded.get(key) != current.get(key)
    )
    return ", ".join(differing) or "no field differs, but the objects compare unequal"


def _describe_message_drift(
    recorded: Sequence[Any], sent: Sequence[Any], *, width: int = 400
) -> str:
    if len(recorded) != len(sent):
        return (
            f"  cassette has {len(recorded)} messages, the loop sent {len(sent)}"
        )
    for index, (before, after) in enumerate(zip(recorded, sent)):
        if before != after:
            return (
                f"  messages[{index}] differs\n"
                f"    cassette: {json.dumps(before)[:width]}\n"
                f"    loop:     {json.dumps(after)[:width]}"
            )
    return "  the messages compare equal; the difference is elsewhere"
