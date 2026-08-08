"""File-inspection tools the agent can call.

These are ordinary functions. They know nothing about the model, the API, or the
agent loop: they take a repository root plus plain arguments and return text.

Every path that crosses this boundary is untrusted — it was chosen by the model —
so it is resolved and confined to the root before any file is opened.
"""

from __future__ import annotations

import re
from pathlib import Path

# Caps exist because tool output becomes prompt tokens. An uncapped search across a
# large repo would blow the context window and cost real money for no benefit.
MAX_SEARCH_MATCHES = 50
MAX_LISTED_FILES = 200
MAX_READ_LINES = 400
MAX_FILE_BYTES = 1_000_000

IGNORED_DIRS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "venv",
    }
)


class ToolError(Exception):
    """A tool failed in a way the model can recover from by trying something else."""


def _resolve_within(root: Path, candidate: str) -> Path:
    """Resolve `candidate` against `root` and confine the result to it.

    Resolving first and comparing after is what makes this safe: it collapses `..`
    and follows symlinks, so an escape shows up as a path outside the root rather
    than as a string that merely looks harmless.
    """
    root = root.resolve()
    try:
        resolved = (root / candidate).resolve()
    except OSError as exc:
        raise ToolError(f"Could not resolve path {candidate!r}: {exc}") from exc

    if resolved != root and not resolved.is_relative_to(root):
        raise ToolError(
            f"Path {candidate!r} is outside the repository root. "
            "Only paths inside the repository can be read."
        )
    return resolved


def _iter_files(root: Path):
    """Yield every readable file under `root`, skipping vendor dirs and symlinks."""
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED_DIRS for part in relative.parts):
            continue
        # Symlinks are skipped rather than confined: a link inside the repo can point
        # anywhere, and following it would sidestep _resolve_within entirely.
        if path.is_symlink() or not path.is_file():
            continue
        yield path


def list_files(root: Path, pattern: str = "**/*") -> str:
    """List files in the repository, optionally filtered by a glob pattern.

    Args:
        root: Repository root.
        pattern: Glob relative to the root, e.g. `**/*.py` or `src/**/*.ts`.
    """
    root = root.resolve()
    try:
        matched = {p.resolve() for p in root.glob(pattern)}
    except (ValueError, OSError) as exc:
        raise ToolError(f"Invalid glob pattern {pattern!r}: {exc}") from exc

    paths = [p.relative_to(root) for p in _iter_files(root) if p.resolve() in matched]
    if not paths:
        return f"No files match {pattern!r}."

    shown = paths[:MAX_LISTED_FILES]
    lines = [str(p) for p in shown]
    if len(paths) > len(shown):
        lines.append(f"... {len(paths) - len(shown)} more files not shown.")
    return "\n".join(lines)


def search(root: Path, pattern: str, glob: str = "**/*") -> str:
    """Search the repository for a regular expression, returning matching lines.

    Args:
        root: Repository root.
        pattern: Python regular expression. Prefix with `(?i)` for case-insensitive.
        glob: Restrict the search to files matching this glob.
    """
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ToolError(f"Invalid regular expression {pattern!r}: {exc}") from exc

    root = root.resolve()
    try:
        allowed = {p.resolve() for p in root.glob(glob)}
    except (ValueError, OSError) as exc:
        raise ToolError(f"Invalid glob pattern {glob!r}: {exc}") from exc

    matches: list[str] = []
    truncated = False
    for path in _iter_files(root):
        if path.resolve() not in allowed or path.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # Binary or unreadable; not something the model can use.

        for number, line in enumerate(text.splitlines(), start=1):
            if not regex.search(line):
                continue
            if len(matches) >= MAX_SEARCH_MATCHES:
                truncated = True
                break
            matches.append(f"{path.relative_to(root)}:{number}: {line.strip()}")
        if truncated:
            break

    if not matches:
        return f"No matches for {pattern!r}."
    if truncated:
        matches.append(
            f"... stopped at {MAX_SEARCH_MATCHES} matches. Narrow the pattern or glob."
        )
    return "\n".join(matches)


def read_file(
    root: Path,
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Read a file, returning numbered lines.

    Args:
        root: Repository root.
        path: File path relative to the root.
        start_line: First line to return, 1-indexed. Defaults to the start of the file.
        end_line: Last line to return, inclusive. Defaults to the end of the file.
    """
    resolved = _resolve_within(root, path)
    if not resolved.exists():
        raise ToolError(f"No such file: {path!r}")
    if not resolved.is_file():
        raise ToolError(f"{path!r} is a directory, not a file.")

    try:
        text = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError(f"{path!r} is not a UTF-8 text file.") from exc
    except OSError as exc:
        raise ToolError(f"Could not read {path!r}: {exc}") from exc

    lines = text.splitlines()
    start = max(1, start_line or 1)
    end = min(len(lines), end_line or len(lines))
    if start > len(lines):
        raise ToolError(f"{path!r} has only {len(lines)} lines; {start} is past the end.")

    selected = lines[start - 1 : end]
    truncated = len(selected) > MAX_READ_LINES
    selected = selected[:MAX_READ_LINES]

    width = len(str(start + len(selected) - 1))
    body = "\n".join(
        f"{number:>{width}} | {line}"
        for number, line in enumerate(selected, start=start)
    )
    if truncated:
        body += (
            f"\n... stopped at {MAX_READ_LINES} lines. "
            "Use start_line and end_line to read a specific range."
        )
    return body
