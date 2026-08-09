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
| `agent/usage.py` | Token accounting and cost for a run. |
| `agent/__main__.py` | The CLI. |
| `agent/probe.py` | A debugging entry point: one live request, printed in full, with no loop and nothing executed. |

Still to come: the record/replay test harness.

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

There is no test suite yet; that arrives with the record/replay harness. In the
meantime the loop can be exercised offline by passing it a stand-in client, since
`run()` takes the client as an argument rather than constructing one.
