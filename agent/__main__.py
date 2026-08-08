"""CLI entry point: ask one question about a repository.

    uv run python -m agent "Which file defines ToolError?"
    uv run python -m agent --repo ~/some/project "Where is retry configured?"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import anthropic

from agent.loop import MAX_TURNS, run


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="agent", description="Ask a question about a local codebase."
    )
    parser.add_argument("question", help="The question to answer.")
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Repository to inspect. Defaults to the current directory.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=MAX_TURNS,
        help=f"Give up after this many model turns (default {MAX_TURNS}).",
    )
    args = parser.parse_args()

    root = args.repo.expanduser().resolve()
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 2

    result = run(
        anthropic.Anthropic(), root, args.question, max_turns=args.max_turns
    )

    # The answer goes to stdout and everything else to stderr, so the answer stays
    # pipeable.
    print(result.answer)
    print(f"\n[{result.turns} turns] {result.usage}", file=sys.stderr)

    if result.stopped_early:
        print(
            f"warning: hit the {args.max_turns}-turn cap before the model finished; "
            "the answer above is incomplete",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
