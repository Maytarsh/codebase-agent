"""CLI entry point: ask one question about a repository.

    uv run python -m agent "Which file defines ToolError?"
    uv run python -m agent --repo ~/some/project "Where is retry configured?"
    uv run python -m agent --json "Which file defines ToolError?" | jq .citations
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import anthropic

from agent.loop import MAX_TURNS, Result, run


def render(result: Result) -> str:
    """Human-readable form of a structured answer."""
    answer = result.answer
    if answer is None:
        return result.partial_text or "(no answer produced)"

    lines = [answer.answer, ""]
    if answer.citations:
        lines.append("evidence:")
        width = max(len(f"{c.path}:{c.line}") for c in answer.citations)
        for citation in answer.citations:
            location = f"{citation.path}:{citation.line}"
            lines.append(f"  {location:<{width}}  {citation.detail}")
        lines.append("")
    lines.append(f"confidence: {answer.confidence}")
    return "\n".join(lines)


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
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the answer as JSON, for scoring a batch of questions.",
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
    # pipeable — into jq, or into a scoring script.
    if args.json:
        print(result.answer.model_dump_json(indent=2) if result.answer else "null")
    else:
        print(render(result))

    print(f"\n[{result.turns} turns] {result.usage}", file=sys.stderr)

    if result.stopped_early:
        print(
            f"warning: hit the {args.max_turns}-turn cap before the model finished; "
            "no structured answer was produced",
            file=sys.stderr,
        )
        return 1
    if result.answer is None:
        print(
            "warning: the model stopped without producing a structured answer",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
