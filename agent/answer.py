"""The shape of a final answer.

Constraining the last response to a schema turns "did it get this right?" from a
reading exercise into a field comparison. That is what makes measuring accuracy
across a set of questions cheap enough to actually do — and it is the reason
these models are worth the dependency, unlike the hand-written tool schemas in
schemas.py: this data comes back from the model, so it genuinely needs validating.

The field descriptions are not documentation. They are sent to the model as part
of the schema and are the main lever on what comes back — the three-sentence
limit below does more to control verbosity than anything in the system prompt.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Citation(BaseModel):
    """One piece of evidence, checkable by opening the file at that line."""

    # Renders as additionalProperties: false, which strict schemas require.
    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="File path, relative to the repository root.")
    line: int = Field(description="1-indexed line number the claim rests on.")
    detail: str = Field(
        description="What this line shows, in one short sentence."
    )


class Answer(BaseModel):
    """A final answer plus the evidence it rests on."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(
        description=(
            "The answer to the question, in at most three sentences. Plain prose: "
            "no markdown headings, no bullet lists, no code blocks. Answer only "
            "what was asked and stop."
        )
    )
    citations: list[Citation] = Field(
        description=(
            "Every file and line the answer relies on. Cite what you actually "
            "read, not what you assume is there."
        )
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description=(
            "high when the evidence is direct and complete; medium when it is "
            "partial or inferred; low when the repository did not really answer "
            "the question."
        )
    )
