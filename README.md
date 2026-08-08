# codebase-agent

Ask questions about a local codebase. A tool-using agent built directly on the
Claude API — no framework — with a record/replay harness that makes its tests
deterministic and offline.

The finished interface is a single question against a repository:

```
codebase-agent --repo ~/some/project "Which file defines parse_config, and what calls it?"
```

## Status

Built one section at a time. What exists today:

| Path | What it is |
|---|---|
| `agent/tools.py` | The three tools the agent calls: `list_files`, `search`, `read_file`. They know nothing about the model or the API. Paths chosen by the model are resolved and confined to the repository root before any file is opened, and every result is capped, because tool output becomes prompt tokens. |
| `agent/schemas.py` | The same three tools described in JSON Schema, each kept in one object alongside the function that implements it. The seam between plain Python and the API. |
| `agent/probe.py` | A debugging entry point: sends one live request and prints the response, without executing tools or looping. Useful for seeing the wire format directly. |

Still to come: the agent loop, structured output, the CLI entry point, and the
record/replay test harness.

## Development

Managed with [uv](https://docs.astral.sh/uv/).

```sh
uv sync    # create .venv and install dependencies, including dev
```

There is no CLI entry point and no test suite yet. To exercise the tools
directly in the meantime:

```sh
uv run python -c "
from pathlib import Path
from agent.tools import search
print(search(Path('.'), r'^def ', '**/*.py'))
"
```

To see what the API sends back when the tools are declared — one request, no
loop, nothing executed. Needs `ANTHROPIC_API_KEY` and costs a fraction of a cent:

```sh
uv run python -m agent.probe
uv run python -m agent.probe "Where is the path confinement implemented?"
```
