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

Still to come: tool schemas, the agent loop, structured output, the CLI entry
point, and the record/replay test harness.

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
