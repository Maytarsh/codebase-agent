# codebase-agent

Ask questions about a local codebase. A tool-using agent built directly on the
Claude API — no framework — with a record/replay harness that makes its tests
deterministic and offline.

```sh
uv run python -m agent --repo ~/some/project "Which file defines parse_config, and what calls it?"
```

## Status

Built one section at a time. What exists today:

| Path | What it is |
|---|---|
| `agent/tools.py` | The three tools the agent calls: `list_files`, `search`, `read_file`. They know nothing about the model or the API. Paths chosen by the model are resolved and confined to the repository root before any file is opened, and every result is capped, because tool output becomes prompt tokens. |
| `agent/schemas.py` | The same three tools described in JSON Schema, each kept in one object alongside the function that implements it. The seam between plain Python and the API. |
| `agent/answer.py` | The shape of a final answer — prose, citations, confidence — enforced by the API rather than hoped for. Turns "is this right?" into a field comparison instead of an essay review. |
| `agent/loop.py` | The agent: dispatch tool calls, feed results back, repeat until the model stops asking. Handles parallel calls, turns recoverable failures into `is_error` results, and stops at a turn cap. |
| `agent/client.py` | The seam between the loop and the network — one method, three implementations: live, recording, replaying. The loop never imports the SDK. |
| `agent/usage.py` | Token accounting and cost for a run. |
| `agent/__main__.py` | The CLI. |
| `agent/probe.py` | A debugging entry point: one live request, printed in full, with no loop and nothing executed. |
| `tests/` | The five failure modes of the loop, replayed from cassettes. |

## Measurement

Ten questions about this repository, each with the file a correct answer has to
cite, and one variable changed between runs:

```sh
uv run python bench/run.py --descriptions good                    # control
uv run python bench/run.py --descriptions vague                   # what the tools do
uv run python bench/run.py --descriptions vague --system terse    # …and no hint anywhere
```

Tool descriptions are the only thing the model sees when deciding whether to
call a tool, so they are prompt engineering with a bill attached. The shipped
ones say *when* to reach for each tool; `vague` swaps in the version most people
write first and changes nothing else. Degrading a tuned description is one
variable — tuning a vague one until the number improves would confound the
change with everything tried along the way.

That third run exists because the first two were not one variable. The system
prompt also says "search before you read", so `vague` alone had removed one of
two copies of the guidance rather than the guidance. `--system terse` drops that
sentence too, and the flags stay separate so an effect could be attributed to
one of them. The mistake, and what it cost, are in the write-up.

Roughly $1 a run. Scoring is on cited files, which is mechanical; the prose you
read yourself.

**The result was a null**, and [`bench/RESULTS.md`](bench/RESULTS.md) is the
write-up: 10/10 in every condition, a two-turn spread across all three — the
same as the spread on one question. The interesting part is why the task turned
out to have no headroom, and what would need to change to measure the effect at
all.

## Development

Managed with [uv](https://docs.astral.sh/uv/).

```sh
uv sync    # create .venv and install dependencies, including dev
```

Ask a question. Needs `ANTHROPIC_API_KEY`. The answer goes to stdout; turn count
and cost go to stderr, so the answer stays pipeable:

```sh
uv run python -m agent "Which file defines ToolError, and what raises it?"
uv run python -m agent --repo ~/other/project --max-turns 5 "How is retry configured?"
```

Answers come back as a fixed structure — a short prose answer, one citation per
file and line it relied on, and a confidence level. `--json` emits that structure
directly, which is what makes scoring a batch of questions scriptable:

```sh
uv run python -m agent --json "Which file defines ToolError?" | jq '.citations[].path'
```

See one raw response without running the loop or executing any tool — the same
model, system prompt and tools the agent uses, stopped after the first turn:

```sh
uv run python -m agent.probe
```

## Tests

An agent's output is different every run, so there is no stable string to assert
on. The fix is to stop asking: `run()` takes its model client as an argument, and
the tests pass one that reads recorded responses off disk instead of calling the
API.

```sh
uv run pytest
```

That needs no API key and no network. It is the deliverable — try it with the
Wi-Fi off.

Five cassettes in `tests/cassettes/`, one per failure mode the loop actually has:
the happy path, recovery from a tool error, the turn cap, a rejected path
traversal, and parallel tool calls returned in a single message. A sixth file
tests the harness itself — that a cassette recorded against a different system
prompt, tool set, or question fails loudly rather than replaying the wrong
response while the assertions still pass.

Questions are asked of `tests/fixture_repo/`, a three-file project that exists
only to hold still. Tool results are part of a recorded conversation, so pointing
the tests at this repository would invalidate every cassette on each edit.

Record a cassette from the live API, and replay it — the same command with one
word changed:

```sh
uv run python -m agent --repo tests/fixture_repo --record /tmp/session.json "Which file defines add?"
uv run python -m agent --repo tests/fixture_repo --replay /tmp/session.json "Which file defines add?"
```

Four of the five committed cassettes are not live recordings. Their model
responses are written by hand in `tests/make_cassettes.py` and pushed through the
same recording client, which is the whole advantage of the format: a model that
never stops calling tools, or one that asks for `/etc/passwd`, becomes a fixture
you author rather than a recording you wait for. The tool results in them are
real either way — the loop runs the actual tools while recording.

`happy_path.json` is the exception, and deliberately so. An authored response
encodes what its author believed the API returns, so a suite built only on them
can be green against a fiction. This one was: the authored version had the model
searching serially, one tool call per turn, while the live recording that
replaced it calls two tools in parallel on both turns. Keep one cassette that
reality wrote.

```sh
uv run python tests/make_cassettes.py    # rebuild the four authored ones
```

Re-recording the live one is the `--record` command above. Both are needed after
a change to the system prompt, the tool schemas, the answer schema, or the
fixture repository.

**What these tests do not cover.** The seam sits above HTTP, so they exercise the
loop but not request construction or serialization — a malformed tool schema
would replay perfectly. Intercepting at the transport layer instead, which is
what [VCR.py](https://vcrpy.readthedocs.io/) and
[pytest-recording](https://pypi.org/project/pytest-recording/) do, covers both at
the cost of coupling the tests to httpx internals. They also say nothing about
whether the answers are any good; that is quality scoring, and it is a different
job.

Cassettes contain no credentials — the API key lives in HTTP headers, a layer
below this seam — but they do contain the system prompt, the question, and the
contents of every file the tools read. Record against a repository you would be
happy to commit.
