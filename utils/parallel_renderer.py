"""
Parallel Manim rendering engine.

Uses ``concurrent.futures.ProcessPoolExecutor`` to render multiple
Manim scenes simultaneously, taking advantage of multi-core CPUs
(especially Apple M-series chips with 10-12 performance cores).
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Optional

from utils.manim_runner import run_manim_code, extract_class_name


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
                result = RenderResult(segment_id=seg_id, success=False, error=str(exc))

            results_map[seg_id] = result
            if on_complete:
                on_complete(result)

    # Return in original job order
    return [results_map[job.segment_id] for job in jobs]


def render_two_pass(
    jobs: list[RenderJob],
    max_workers: int | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> list[RenderResult]:
    """Two-pass render: fast ``-ql`` first, then ``-qh`` for successes.

    This mimics the existing single-scene logic but across all segments
    in parallel.

    Returns the HD results where possible, falling back to QL results.
    """
    if on_progress:
        on_progress("Starting fast preview render (-ql) for all segments...")

    # Pass 1: Quick render
    ql_jobs = [RenderJob(
        segment_id=j.segment_id,
        code=j.code,
        class_name=j.class_name,
        quality_flag="-ql",
        timeout_seconds=j.timeout_seconds,
        output_dir=j.output_dir,
    ) for j in jobs]

    ql_results = render_parallel(ql_jobs, max_workers=max_workers)

    # Pass 2: HD render for successful segments
    hd_jobs = []
    ql_map: dict[int, RenderResult] = {}
    for r in ql_results:
        ql_map[r.segment_id] = r
        if r.success:
            orig = next(j for j in jobs if j.segment_id == r.segment_id)
            hd_jobs.append(RenderJob(
                segment_id=r.segment_id,
                code=orig.code,
                class_name=orig.class_name,
                quality_flag="-qh",
                timeout_seconds=300,
                output_dir=orig.output_dir,
            ))

    if not hd_jobs:
        if on_progress:
            on_progress("No segments passed preview render. Skipping HD pass.")
        return ql_results

    if on_progress:
        on_progress(f"Starting HD render (-qh) for {len(hd_jobs)} segments...")

    hd_results = render_parallel(hd_jobs, max_workers=max_workers)
    hd_map = {r.segment_id: r for r in hd_results}

    # Merge: prefer HD, fall back to QL
    final: list[RenderResult] = []
    for job in jobs:
        sid = job.segment_id
        if sid in hd_map and hd_map[sid].success:
            final.append(hd_map[sid])
        elif sid in ql_map:
            final.append(ql_map[sid])
        else:
            final.append(RenderResult(segment_id=sid, success=False, error="Not rendered"))

    return final
