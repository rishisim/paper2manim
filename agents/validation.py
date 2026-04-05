"""Input validation for the paper2manim pipeline."""

from __future__ import annotations


def validate_concept(concept: str) -> str:
    """Validate and sanitize the concept string.

    Returns the cleaned concept string, or raises ``ValueError``
    with a human-readable message if the input is invalid.
    """
    if not isinstance(concept, str):
        raise ValueError("Concept must be a string")

    concept = concept.strip()

    if not concept:
        raise ValueError("Concept cannot be empty")

    if len(concept) > 2000:
        raise ValueError(
            f"Concept too long ({len(concept)} chars, max 2000)"
        )

    return concept
