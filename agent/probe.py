"""One live API call, printed in full.

Run this before writing any loop code. It sends a single request with the tools
declared and prints what comes back, without executing anything — so you can see
an actual `tool_use` block before writing code that handles one.

    uv run python -m agent.probe
    uv run python -m agent.probe "Where is the path confinement implemented?"

This is a debugging entry point, not part of the agent. It never calls a tool and
never loops: it stops at the model's first response.
"""

from __future__ import annotations

import json
import sys

import anthropic

from agent.schemas import api_schemas

MODEL = "claude-opus-5"
MAX_TOKENS = 4096

# USD per million tokens, from the Claude API pricing page.
INPUT_COST_PER_MTOK = 5.00
OUTPUT_COST_PER_MTOK = 25.00

SYSTEM = (
    "You answer questions about a code repository by calling the tools provided. "
    "Always cite file paths and line numbers. Use the tools rather than guessing "
    "from prior knowledge."
)

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

    usage = response.usage
    cache_read = usage.cache_read_input_tokens or 0
    cache_write = usage.cache_creation_input_tokens or 0
    cost = (
        usage.input_tokens * INPUT_COST_PER_MTOK
        + usage.output_tokens * OUTPUT_COST_PER_MTOK
    ) / 1_000_000

    print(
        f"\nusage: input={usage.input_tokens} output={usage.output_tokens} "
        f"cache_read={cache_read} cache_write={cache_write}"
    )
    # input_tokens counts only the uncached remainder, so the real prompt size is
    # the sum of all three input figures.
    print(f"prompt tokens total: {usage.input_tokens + cache_read + cache_write}")
    print(f"cost: ${cost:.6f}")

    print("\n--- raw response ---")
    print(response.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
