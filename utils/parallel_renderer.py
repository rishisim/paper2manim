"""
Parallel Manim rendering engine.

Uses ``concurrent.futures.ProcessPoolExecutor`` to render multiple
Manim scenes simultaneously, taking advantage of multi-core CPUs
(especially Apple M-series chips with 10-12 performance cores).
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

from utils.manim_runner import extract_class_name, run_manim_code

logger = logging.getLogger(__name__)


@dataclass
class RenderJob:
    """A single Manim render task."""

    segment_id: int
    code: str
    class_name: str = ""
    quality_flag: str = "-ql"
    timeout_seconds: int = 120
    output_dir: str | None = None

    def __post_init__(self):
        if not self.class_name:
            self.class_name = extract_class_name(self.code)


@dataclass
class RenderResult:
    """Result of a single render job."""

    segment_id: int
    success: bool
    video_path: str | None = None
    error: str | None = None


def _render_single(job: RenderJob) -> RenderResult:
    """Worker function executed in a subprocess."""
    try:
        result = run_manim_code(
            code=job.code,
            class_name=job.class_name,
            quality_flag=job.quality_flag,
            timeout_seconds=job.timeout_seconds,
            output_dir=job.output_dir,
        )
        return RenderResult(
            segment_id=job.segment_id,
            success=result["success"],
            video_path=result.get("video_path"),
            error=result.get("error"),
        )
    except Exception as exc:
        logger.error("Render worker crashed for segment %d: %s", job.segment_id, exc)
        return RenderResult(
            segment_id=job.segment_id,
            success=False,
            error=str(exc),
        )


def render_parallel(
    jobs: list[RenderJob],
    max_workers: int | None = None,
    on_complete: Callable[[RenderResult], None] | None = None,
) -> list[RenderResult]:
    """Render multiple Manim scenes in parallel.

    Args:
        jobs: List of ``RenderJob`` instances to render.
        max_workers: Max parallel processes.  Defaults to ``min(len(jobs), os.cpu_count() - 1)``.
        on_complete: Optional callback invoked as each job finishes.

    Returns:
        List of ``RenderResult`` in the **same order** as *jobs*.
    """
    if not jobs:
        return []

    if max_workers is None:
        cpu = os.cpu_count() or 4
        max_workers = min(len(jobs), max(1, cpu - 1))

    results_map: dict[int, RenderResult] = {}

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_id = {
            executor.submit(_render_single, job): job.segment_id for job in jobs
        }

        for future in as_completed(future_to_id):
            seg_id = future_to_id[future]
            try:
                result = future.result()
            except Exception as exc:
                logger.error("Future result retrieval failed for segment %d: %s", seg_id, exc)
                result = RenderResult(segment_id=seg_id, success=False, error=str(exc))

            results_map[seg_id] = result
            if on_complete:
                on_complete(result)

    # Return in original job order
    return [results_map[job.segment_id] for job in jobs]
