"""The tools as the model sees them, paired with the code that implements them.

`tools.py` deliberately knows nothing about the model or the API. This module is
the seam between the two: it describes each tool in the JSON Schema the API
expects, and keeps that description attached to the function that runs it.

Schema and implementation live in one object on purpose. Two parallel structures
— a list of schemas and a separate name-to-function mapping — drift apart, and
the failure shows up at runtime as a tool the model can call but nothing can
execute.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent import tools


@dataclass(frozen=True)
class Tool:
    """One tool: its API-facing description and the function behind it."""

    name: str
    description: str
    properties: dict[str, Any]
    required: tuple[str, ...]
    run: Callable[..., str]

    def api_schema(self) -> dict[str, Any]:
        """Render this tool in the shape the Messages API expects."""
        return {
            "name": self.name,
            "description": self.description,
            # strict + additionalProperties:false makes the API guarantee that
            # `tool_use.input` validates against this schema, so the dispatcher
            # never has to defend against invented or misspelled arguments.
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": self.properties,
                "required": list(self.required),
                "additionalProperties": False,
            },
        }


# `root` appears in none of these schemas. The repository root is bound by the
# harness, never chosen by the model — exposing it would hand over the single
# parameter that the path confinement in tools.py exists to control.
#
# Descriptions say *when* to reach for a tool, not just what it does. That
# wording is the only thing the model sees when deciding, and it moves the
# numbers more than almost anything else here.
TOOLS: tuple[Tool, ...] = (
    Tool(
        name="list_files",
        description=(
            "List files in the repository. Call this first to get oriented when you "
            "do not know the layout yet. Prefer a narrow glob over listing everything."
        ),
        properties={
            "pattern": {
                "type": "string",
                "description": (
                    "Glob relative to the repository root, e.g. '**/*.py' or "
                    "'src/**/*.ts'. Omit to list every file."
                ),
            },
        },
        required=(),
        run=tools.list_files,
    ),
    Tool(
        name="search",
        description=(
            "Search the repository for a regular expression and return matching "
            "lines with their file paths and line numbers. Call this before "
            "read_file whenever you do not already know which file to open — it is "
            "far cheaper than reading files one by one."
        ),
        properties={
            "pattern": {
                "type": "string",
                "description": (
                    "Python regular expression. Prefix with '(?i)' for a "
                    "case-insensitive search."
                ),
            },
            "glob": {
                "type": "string",
                "description": "Restrict the search to files matching this glob.",
            },
        },
        required=("pattern",),
        run=tools.search,
    ),
    Tool(
        name="read_file",
        description=(
            "Read a file and return its lines, numbered. Call this once search has "
            "told you which file matters, and pass a line range when you only need "
            "part of a large file."
        ),
        properties={
            "path": {
                "type": "string",
                "description": "File path relative to the repository root.",
            },
            "start_line": {
                "type": "integer",
                "description": "First line to return, 1-indexed. Omit to start at the top.",
            },
            "end_line": {
                "type": "integer",
                "description": "Last line to return, inclusive. Omit to read to the end.",
            },
        },
        required=("path",),
        run=tools.read_file,
    ),
)

TOOLS_BY_NAME: dict[str, Tool] = {tool.name: tool for tool in TOOLS}


def api_schemas() -> list[dict[str, Any]]:
    """Every tool, in the shape the `tools` request parameter expects."""
    return [tool.api_schema() for tool in TOOLS]
