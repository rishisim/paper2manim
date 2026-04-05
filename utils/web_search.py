"""
Web search utility for the Manim coder agent.

Uses Google Custom Search JSON API when credentials are available,
otherwise falls back to a simple requests-based scraper that fetches
content from known reference sites (StackOverflow, GitHub, Manim docs).

The ``search_web`` function is designed to be registered as a Gemini
callable tool so the LLM can autonomously look up code examples,
library APIs, or animation techniques while generating Manim scripts.
"""

from __future__ import annotations

import logging
import os
import re
import textwrap
from functools import lru_cache
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 10  # seconds per HTTP request


# ── Google Custom Search (preferred when credentials exist) ───────────

def _google_search(query: str, num_results: int = 5) -> list[dict]:
    """Return up to *num_results* via Google Custom Search JSON API.

    Requires ``GOOGLE_CSE_API_KEY`` and ``GOOGLE_CSE_ID`` env-vars.
    Returns a list of ``{"title", "link", "snippet"}`` dicts.
    """
    api_key = os.getenv("GOOGLE_CSE_API_KEY", "")
    cse_id = os.getenv("GOOGLE_CSE_ID", "")
    if not api_key or not cse_id:
        return []

    url = "https://www.googleapis.com/customsearch/v1"
    params = {"key": api_key, "cx": cse_id, "q": query, "num": min(num_results, 10)}

    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        return [
            {
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            }
            for item in items[:num_results]
        ]
    except requests.RequestException as e:
        logger.warning("Google CSE search failed: %s", e)
        return []
    except (KeyError, ValueError) as e:
        logger.warning("Failed to parse Google CSE response: %s", e)
        return []


# ── Lightweight page content fetcher ──────────────────────────────────

_STRIP_RE = re.compile(r"<[^>]+>")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")


def _fetch_page_text(url: str, max_chars: int = 8_000) -> str:
    """Fetch a URL and return a rough plain-text version of the page body."""
    try:
        resp = requests.get(
            url,
            timeout=_TIMEOUT,
            headers={"User-Agent": "Paper2Manim-Bot/1.0"},
        )
        resp.raise_for_status()
        text = resp.text

        # Very rough HTML → text (we avoid pulling in BeautifulSoup)
        # Remove <script> and <style> blocks entirely
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = _STRIP_RE.sub(" ", text)
        text = _MULTI_SPACE_RE.sub(" ", text).strip()

        return text[:max_chars]
    except requests.RequestException as exc:
        logger.warning("Failed to fetch page %s: %s", url, exc)
        return f"[Failed to fetch {url}: {exc}]"


# ── Public tool callable by the LLM ──────────────────────────────────

def search_web(query: str) -> str:
    """Search the web for Manim code examples, Python libraries, or animation techniques.

    Use this tool when you need to:
    - Find code examples for a specific Manim animation or effect
    - Look up a Python library's API or usage patterns
    - Find solutions to specific Manim rendering issues
    - Discover community-created Manim utilities or plugins

    Args:
        query: A search query describing what you're looking for.
               Be specific, e.g. "manim 3D surface plot example"
               or "python library for bezier curve interpolation".

    Returns:
        A summary of search results with titles, URLs, and snippets.
        If a result looks highly relevant, its page content is included.
    """
    # Always add "manim" or "python" context to improve results
    enriched_query = query
    if "manim" not in query.lower() and "python" not in query.lower():
        enriched_query = f"python manim {query}"

    results = _google_search(enriched_query)

    if not results:
        # Fallback: search known sites directly
        results = _fallback_search(enriched_query)

    if not results:
        return f"No search results found for: {query}"

    parts: list[str] = [f"=== Web Search Results for: {query} ===\n"]

    for i, r in enumerate(results[:5], 1):
        parts.append(f"[{i}] {r['title']}")
        parts.append(f"    URL: {r['link']}")
        parts.append(f"    {r['snippet']}")
        parts.append("")

    # Fetch the top 2 most relevant pages for deeper context
    for r in results[:2]:
        url = r["link"]
        if any(
            domain in url
            for domain in [
                "stackoverflow.com",
                "github.com",
                "docs.manim.community",
                "pypi.org",
            ]
        ):
            parts.append(f"\n--- Fetched content from: {url} ---")
            parts.append(_fetch_page_text(url, max_chars=6_000))
            parts.append("")

    output = "\n".join(parts)
    # Truncate to a reasonable size for prompt context
    if len(output) > 25_000:
        output = output[:25_000] + "\n\n... [truncated]"
    return output


def _fallback_search(query: str) -> list[dict]:
    """Search known reference sites when Google CSE is not configured."""
    results = []

    # Try GitHub code search via the web (unauthenticated, limited)
    try:
        gh_url = f"https://api.github.com/search/code?q={requests.utils.quote(query)}+language:python&per_page=5"
        resp = requests.get(
            gh_url,
            timeout=_TIMEOUT,
            headers={
                "Accept": "application/vnd.github.v3.text-match+json",
                "User-Agent": "Paper2Manim-Bot/1.0",
            },
        )
        if resp.ok:
            for item in resp.json().get("items", [])[:3]:
                snippet = ""
                for tm in item.get("text_matches", []):
                    snippet += tm.get("fragment", "") + " "
                results.append(
                    {
                        "title": item.get("name", ""),
                        "link": item.get("html_url", ""),
                        "snippet": snippet.strip()[:300] or item.get("path", ""),
                    }
                )
    except requests.RequestException as e:
        logger.warning("GitHub code search failed: %s", e)
    except (KeyError, ValueError) as e:
        logger.warning("Failed to parse GitHub search response: %s", e)

    # Try StackOverflow tagged search
    try:
        so_url = (
            "https://api.stackexchange.com/2.3/search/advanced"
            f"?order=desc&sort=relevance&q={requests.utils.quote(query)}"
            "&site=stackoverflow&pagesize=3&filter=withbody"
        )
        resp = requests.get(so_url, timeout=_TIMEOUT)
        if resp.ok:
            for item in resp.json().get("items", [])[:3]:
                results.append(
                    {
                        "title": item.get("title", ""),
                        "link": item.get("link", ""),
                        "snippet": _STRIP_RE.sub("", item.get("body", ""))[:300],
                    }
                )
    except requests.RequestException as e:
        logger.warning("StackOverflow search failed: %s", e)
    except (KeyError, ValueError) as e:
        logger.warning("Failed to parse StackOverflow response: %s", e)

    return results
