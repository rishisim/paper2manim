"""
Fetch Manim documentation and source code directly from the GitHub repository.

Uses raw.githubusercontent.com to retrieve plain-text .py and .rst files —
no HTML scraping or extra parsing libraries required.  Results are cached
in-memory for the lifetime of the process so repeated look-ups are free.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional

import requests

REPO_BASE = (
    "https://raw.githubusercontent.com/ManimCommunity/manim/main"
)

_FETCH_TIMEOUT = 15  # seconds

# ---------------------------------------------------------------------------
# Source-file registry: maps short topic keys to the repo paths that document
# them.  The model receives this index so it can decide what to fetch.
# ---------------------------------------------------------------------------

TOPIC_INDEX: dict[str, list[str]] = {
    # Animations
    "create": ["manim/animation/creation.py"],
    "write": ["manim/animation/creation.py"],
    "transform": ["manim/animation/transform.py"],
    "fade": ["manim/animation/fading.py"],
    "grow": ["manim/animation/growing.py"],
    "indicate": ["manim/animation/indication.py"],
    "rotate": ["manim/animation/rotation.py"],
    "movement": ["manim/animation/movement.py"],
    "composition": ["manim/animation/composition.py"],

    # Mobjects — geometry
    "circle": ["manim/mobject/geometry/arc.py"],
    "dot": ["manim/mobject/geometry/arc.py"],
    "arc": ["manim/mobject/geometry/arc.py"],
    "line": ["manim/mobject/geometry/line.py"],
    "arrow": ["manim/mobject/geometry/line.py"],
    "square": ["manim/mobject/geometry/polygram.py"],
    "rectangle": ["manim/mobject/geometry/polygram.py"],
    "triangle": ["manim/mobject/geometry/polygram.py"],
    "polygon": ["manim/mobject/geometry/polygram.py"],

    # Mobjects — text
    "text": ["manim/mobject/text/text_mobject.py"],
    "tex": ["manim/mobject/text/tex_mobject.py"],
    "mathtex": ["manim/mobject/text/tex_mobject.py"],
    "code": ["manim/mobject/text/code_mobject.py"],

    # Mobjects — graphing
    "axes": ["manim/mobject/graphing/coordinate_systems.py"],
    "numberplane": ["manim/mobject/graphing/coordinate_systems.py"],
    "numberline": ["manim/mobject/graphing/number_line.py"],
    "barchart": ["manim/mobject/graphing/probability.py"],

    # Mobjects — grouping / layout
    "vgroup": ["manim/mobject/types/vectorized_mobject.py"],
    "group": ["manim/mobject/mobject.py"],
    "table": ["manim/mobject/table.py"],
    "matrix": ["manim/mobject/matrix.py"],

    # Mobjects — 3-D
    "threed": ["manim/mobject/three_d/three_dimensions.py"],
    "surface": ["manim/mobject/three_d/three_dimensions.py"],

    # Scene
    "scene": ["manim/scene/scene.py"],
    "movingcamera": ["manim/scene/moving_camera_scene.py"],
    "threedscene": ["manim/scene/three_d_scene.py"],

    # Misc / utilities
    "color": ["manim/utils/color/core.py"],
    "rate_func": ["manim/utils/rate_functions.py"],
    "config": ["manim/_config/utils.py"],

    # Worked examples (great for the model to study)
    "examples": ["example_scenes/basic.py"],

    # Tutorials (RST but still plain-text readable)
    "quickstart": ["docs/source/tutorials/quickstart.rst"],
    "building_blocks": ["docs/source/tutorials/building_blocks.rst"],
}


def get_topic_index_description() -> str:
    """Return a compact human-readable index the model can use to decide
    which topics to look up."""
    lines = ["Available Manim doc topics (pass one as the `topic` argument):"]
    for topic, paths in TOPIC_INDEX.items():
        short_paths = ", ".join(p.split("/")[-1] for p in paths)
        lines.append(f"  {topic:20s} -> {short_paths}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Raw file fetching with caching
# ---------------------------------------------------------------------------

@lru_cache(maxsize=64)
def _fetch_raw(path: str) -> Optional[str]:
    """Fetch a single file from the Manim repo.  Returns None on failure."""
    url = f"{REPO_BASE}/{path}"
    try:
        resp = requests.get(url, timeout=_FETCH_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except Exception:
        return None


def _truncate(text: str, max_chars: int = 30_000) -> str:
    """Keep output within a reasonable size for a prompt."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n... [truncated]"


# ---------------------------------------------------------------------------
# Public API — designed to be registered as a Gemini callable tool
# ---------------------------------------------------------------------------

def fetch_manim_docs(topic: str) -> str:
    """Retrieve Manim source documentation for a topic.

    Args:
        topic: A keyword identifying the Manim concept to look up.
               Must be one of the keys listed in the topic index
               (e.g. "circle", "transform", "text", "axes", "scene",
               "examples", "quickstart").

    Returns:
        The raw source text (Python or RST) from the official Manim
        repository, including docstrings and inline examples.
        Returns an error message if the topic is unknown or the fetch fails.
    """
    key = topic.strip().lower()

    # Try exact match first
    paths = TOPIC_INDEX.get(key)

    # Fuzzy fallback: check if the key is a substring of any topic
    if paths is None:
        for registered_key, registered_paths in TOPIC_INDEX.items():
            if key in registered_key or registered_key in key:
                paths = registered_paths
                break

    if paths is None:
        return (
            f"Unknown topic '{topic}'. "
            f"Available topics: {', '.join(sorted(TOPIC_INDEX.keys()))}"
        )

    parts: list[str] = []
    for path in paths:
        content = _fetch_raw(path)
        if content is not None:
            parts.append(f"# --- {path} ---\n{content}")
        else:
            parts.append(f"# --- {path} --- [fetch failed]")

    return _truncate("\n\n".join(parts))


def fetch_manim_file(file_path: str) -> str:
    """Retrieve any file from the Manim GitHub repository by its path.

    Args:
        file_path: The path relative to the repository root
                   (e.g. "manim/animation/creation.py" or
                   "docs/source/tutorials/quickstart.rst").

    Returns:
        The raw file content, or an error message if not found.
    """
    # Normalise: strip leading slash or repo prefix if someone pastes a URL
    clean = re.sub(r"^(https?://[^/]+/[^/]+/[^/]+/(blob|raw)/[^/]+/)", "", file_path)
    clean = clean.lstrip("/")

    content = _fetch_raw(clean)
    if content is not None:
        return _truncate(content)
    return f"Could not fetch '{clean}' from the Manim repository."
