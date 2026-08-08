"""Token accounting for a run.

Pulled out of the loop because both the loop and the probe need it, and because
"what did that cost?" is a question worth being able to answer precisely rather
than approximately.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# USD per million tokens, from the Claude API pricing page.
INPUT_PER_MTOK = 5.00
OUTPUT_PER_MTOK = 25.00
# Cache reads bill at roughly a tenth of the input rate; writes at 1.25x.
CACHE_READ_PER_MTOK = 0.50
CACHE_WRITE_PER_MTOK = 6.25


@dataclass
class Usage:
    """Running totals across every request in a single run."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, usage: Any) -> None:
        """Accumulate the `usage` block from one API response."""
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        # These two are None rather than 0 when caching is not in play.
        self.cache_read_tokens += usage.cache_read_input_tokens or 0
        self.cache_write_tokens += usage.cache_creation_input_tokens or 0

    @property
    def prompt_tokens(self) -> int:
        """Every token sent.

        `input_tokens` alone is only the *uncached remainder*, so reading it as
        the prompt size understates the real figure whenever caching is active.
        """
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    @property
    def cost(self) -> float:
        """Cost in USD."""
        return (
            self.input_tokens * INPUT_PER_MTOK
            + self.output_tokens * OUTPUT_PER_MTOK
            + self.cache_read_tokens * CACHE_READ_PER_MTOK
            + self.cache_write_tokens * CACHE_WRITE_PER_MTOK
        ) / 1_000_000

    def __str__(self) -> str:
        return (
            f"prompt={self.prompt_tokens} "
            f"(uncached={self.input_tokens}, cache_read={self.cache_read_tokens}, "
            f"cache_write={self.cache_write_tokens}) "
            f"output={self.output_tokens} cost=${self.cost:.4f}"
        )
