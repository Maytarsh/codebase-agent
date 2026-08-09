"""Run the question set and print a number.

    uv run python bench/run.py --descriptions good
    uv run python bench/run.py --descriptions vague

This is the measurement the project exists to produce. The code working is not
the result; the result is a score, a turn count, and a paragraph saying what
moved and why.

**The experiment.** Tool descriptions are the only thing the model sees when
deciding whether to call a tool, so they are prompt engineering with a cost
attached. The ones in schemas.py say *when* to reach for each tool — "call this
before read_file whenever you do not already know which file to open" — not just
what it does. `--descriptions vague` swaps in the version most people write
first, and changes nothing else.

Running it the other way round, tuning a vague description until the number
improves, would confound the change with everything else you fiddled with on the
way. Degrading a description that is already written is one variable.

`--system terse` exists because the first run of this benchmark was not that one
variable. It scored 10/10 either way, and the reason was that the system prompt
also says "search before you read" — so the vague condition had removed one of
two copies of an instruction rather than the instruction. `terse` drops that
sentence from the system prompt, which is what makes `--descriptions vague
--system terse` the version of the experiment that actually isolates the
guidance. The two flags stay separate so an effect can be attributed to one.

**This costs real money.** Ten questions is roughly $0.50–0.80 a run at Opus 5
prices, so both conditions come to somewhere near $1.50. Nothing here is cached
between runs.

**On reading the result.** With n=10 a one- or two-answer difference in score is
noise. Turn count is the more sensitive measure, because every question
contributes to it — an agent that has not been told to search first reads files
one at a time, and that shows up long before the accuracy does.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

import anthropic

from agent.client import LiveClient
from agent.loop import Result, run

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent

# The descriptions most people write first: what the tool does, nothing about
# when to reach for it. Names and schemas are untouched, so the agent has
# exactly the same capabilities — only the guidance is gone.
VAGUE_DESCRIPTIONS = {
    "list_files": "Lists the files in the repository.",
    "search": "Searches the repository for a regular expression.",
    "read_file": "Reads a file and returns its contents.",
}


def use_vague_descriptions() -> None:
    """Rewrite the tool descriptions in place, for this process only.

    Patching rather than editing schemas.py keeps the experiment out of the
    shipped code — there is no `if benchmarking` branch in the agent, and no way
    to accidentally commit the degraded version.

    Only `api_schemas()` reads TOOLS, and it reads it at call time, so replacing
    the module global is enough. loop.py holds its own reference to
    TOOLS_BY_NAME, which does not matter here: dispatch is keyed on tool *names*,
    and those are unchanged.
    """
    from agent import schemas

    schemas.TOOLS = tuple(
        dataclasses.replace(tool, description=VAGUE_DESCRIPTIONS[tool.name])
        for tool in schemas.TOOLS
    )


# The sentence in the system prompt that duplicates what the tool descriptions
# say. Removing it is the difference between the two system conditions.
SEARCH_HINT = (
    " Search before you read: searching is far cheaper than opening files "
    "one at a time."
)


def use_terse_system() -> None:
    """Drop the search guidance from the system prompt, for this process only.

    Derived from SYSTEM by removing a sentence rather than written out in full,
    so the two conditions cannot drift apart when the prompt is edited. The
    assertion matters more than it looks: a replace that silently matched
    nothing would leave both conditions identical and produce exactly the
    uninformative null this flag exists to fix.
    """
    from agent import client

    assert SEARCH_HINT in client.SYSTEM, "SYSTEM no longer contains the search hint"
    client.SYSTEM = client.SYSTEM.replace(SEARCH_HINT, "")


def normalize(path: str) -> str:
    """Citations arrive relative to the root, but not always spelled identically."""
    return path.removeprefix("./").strip()


def scored(result: Result, expect_files: list[str]) -> bool:
    """True when every expected file appears among the cited ones.

    A subset check, not equality: citing more than the minimum is not an error,
    and several of these questions have defensible longer answers.
    """
    if result.answer is None:
        return False
    cited = {normalize(citation.path) for citation in result.answer.citations}
    return all(
        any(path == expected or path.endswith("/" + expected) for path in cited)
        for expected in expect_files
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--descriptions",
        choices=("good", "vague"),
        default="good",
        help="Which tool descriptions to run with (default: good).",
    )
    parser.add_argument(
        "--system",
        choices=("full", "terse"),
        default="full",
        help="terse drops the 'search before you read' sentence (default: full).",
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=HERE / "questions.json",
        help="Question set to run.",
    )
    args = parser.parse_args()

    if args.descriptions == "vague":
        use_vague_descriptions()
    if args.system == "terse":
        use_terse_system()

    document = json.loads(args.questions.read_text())
    questions = document["questions"]
    client = LiveClient(anthropic.Anthropic())

    print(
        f"descriptions: {args.descriptions}   system: {args.system}   "
        f"questions: {len(questions)}\n"
    )
    header = f"{'id':<14} {'ok':<4} {'turns':>5} {'cost':>8}  cited"
    print(header)
    print("-" * len(header))

    hits = turns = 0
    cost = 0.0
    failures: list[str] = []

    for question in questions:
        started = time.monotonic()
        try:
            result = run(client, REPO_ROOT, question["question"])
        except Exception as exc:  # keep going; a lost run is money already spent
            failures.append(f"{question['id']}: {type(exc).__name__}: {exc}")
            print(f"{question['id']:<14} {'ERR':<4} {'-':>5} {'-':>8}  {exc}")
            continue

        ok = scored(result, question["expect_files"])
        hits += ok
        turns += result.turns
        cost += result.usage.cost

        cited = ", ".join(
            sorted({normalize(c.path) for c in result.answer.citations})
            if result.answer
            else ["(no answer)"]
        )
        print(
            f"{question['id']:<14} {'yes' if ok else 'NO':<4} {result.turns:>5} "
            f"${result.usage.cost:>7.4f}  {cited}"
        )
        print(f"{'':<14} {time.monotonic() - started:.1f}s", file=sys.stderr)

    answered = len(questions) - len(failures)
    print("-" * len(header))
    print(f"{'TOTAL':<14} {hits}/{answered} correct   {turns} turns   ${cost:.4f}")
    if answered:
        print(
            f"{'':<14} {turns / answered:.1f} turns/question   "
            f"${cost / answered:.4f}/question"
        )
    for failure in failures:
        print(f"failed: {failure}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
