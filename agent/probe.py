"""One live API call, printed in full.

Run this to see what a `tool_use` block actually looks like coming back from the
API, without a loop and without executing anything.

    uv run python -m agent.probe
    uv run python -m agent.probe "Where is the path confinement implemented?"

It sends the same model, system prompt and tools the agent does, so what you see
here is exactly the agent's first turn — it simply stops instead of continuing.
"""

from __future__ import annotations

import json
import sys

import anthropic

from agent.loop import MAX_TOKENS, MODEL, SYSTEM
from agent.schemas import api_schemas
from agent.usage import Usage

DEFAULT_QUESTION = "Which file defines the ToolError class, and what raises it?"


def main() -> None:
    question = " ".join(sys.argv[1:]) or DEFAULT_QUESTION

    # Reads ANTHROPIC_API_KEY from the environment.
    client = anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        tools=api_schemas(),
        messages=[{"role": "user", "content": question}],
    )

    print(f"question:    {question}")
    print(f"model:       {response.model}")
    print(f"stop_reason: {response.stop_reason}")

    print("\ncontent blocks:")
    for index, block in enumerate(response.content):
        print(f"  [{index}] {block.type}")
        if block.type == "text":
            print(f"       {block.text.strip()[:400]}")
        elif block.type == "tool_use":
            print(f"       id:    {block.id}")
            print(f"       name:  {block.name}")
            print(f"       input: {json.dumps(block.input)}")
        elif block.type == "thinking":
            print("       (thinking happened; its text is not returned by default)")

    usage = Usage()
    usage.add(response.usage)
    print(f"\nusage: {usage}")

    print("\n--- raw response ---")
    print(response.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
