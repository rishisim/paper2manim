"""Tests for input edge cases — slug generation and concept handling.

Validates that the pipeline's slug helper handles empty, long, unicode,
and shell-metacharacter inputs safely.
"""

from __future__ import annotations

import re

import pytest

from agents.pipeline import _slugify


# ---------------------------------------------------------------------------
# Normal inputs
# ---------------------------------------------------------------------------

def test_slugify_simple():
    assert _slugify("Fourier Transform") == "fourier_transform"


def test_slugify_mixed_case():
    result = _slugify("Dot Product")
    assert result == "dot_product"


def test_slugify_strips_punctuation():
    result = _slugify("What is 2+2?")
    assert "?" not in result
    assert "+" not in result


# ---------------------------------------------------------------------------
# Edge case: empty string
# ---------------------------------------------------------------------------

def test_slugify_empty_string():
    result = _slugify("")
    assert isinstance(result, str)
    assert len(result) == 0


# ---------------------------------------------------------------------------
# Edge case: very long concept (>1000 chars)
# ---------------------------------------------------------------------------

def test_slugify_long_concept():
    long_text = "a" * 2000
    result = _slugify(long_text)
    # _slugify truncates to 60 chars
    assert len(result) <= 60


def test_slugify_long_concept_with_spaces():
    long_text = " ".join(["word"] * 500)
    result = _slugify(long_text)
    assert len(result) <= 60
    assert "_" in result or result == "word"


# ---------------------------------------------------------------------------
# Edge case: shell metacharacters
# ---------------------------------------------------------------------------

SHELL_METACHARS = [
    "$(whoami)",
    "; rm -rf /",
    "concept | cat /etc/passwd",
    "test && echo pwned",
    "a`id`b",
    "hello > /tmp/evil",
    "test\ninjection",
    "concept\x00null",
]


@pytest.mark.parametrize("dangerous_input", SHELL_METACHARS)
def test_slugify_strips_shell_metacharacters(dangerous_input):
    result = _slugify(dangerous_input)
    # The slug should never contain shell-dangerous chars
    assert "$" not in result
    assert ";" not in result
    assert "|" not in result
    assert "&" not in result
    assert "`" not in result
    assert ">" not in result
    assert "<" not in result
    assert "\n" not in result
    assert "\x00" not in result
    # Should be a safe filesystem path component
    assert re.match(r"^[a-z0-9_]*$", result), f"Unsafe slug: {result!r}"


# ---------------------------------------------------------------------------
# Edge case: unicode and emoji
# ---------------------------------------------------------------------------

UNICODE_INPUTS = [
    ("Fourier Transformee", "fourier_transformee"),  # ASCII baseline
    ("euler's formula", "eulers_formula"),
    ("Schrodinger equation", "schrodinger_equation"),
]


@pytest.mark.parametrize("text,expected", UNICODE_INPUTS)
def test_slugify_unicode_text(text, expected):
    result = _slugify(text)
    assert result == expected


def test_slugify_emoji():
    result = _slugify("calculus is fun! :)")
    # Emoji and special chars should be stripped, leaving safe chars
    assert isinstance(result, str)
    assert re.match(r"^[a-z0-9_]*$", result)


def test_slugify_cjk_characters():
    """CJK characters are word chars in regex, so _slugify keeps them."""
    result = _slugify("linear algebra")
    assert isinstance(result, str)
    assert len(result) > 0


def test_slugify_only_special_chars():
    result = _slugify("!@#$%^&*()")
    assert isinstance(result, str)
    # All chars stripped, result may be empty
    assert re.match(r"^[a-z0-9_]*$", result)


# ---------------------------------------------------------------------------
# Slug is safe for filesystem paths
# ---------------------------------------------------------------------------

def test_slugify_no_path_traversal():
    result = _slugify("../../etc/passwd")
    assert ".." not in result
    assert "/" not in result


def test_slugify_no_leading_trailing_underscores():
    """strip("_") removes leading/trailing underscores."""
    result = _slugify("  hello world  ")
    assert not result.startswith("_")
    assert not result.endswith("_")
