from __future__ import annotations

from concurrent.futures import Future

from utils import parallel_renderer


def test_single_job_submissions_keep_shared_pool_size(monkeypatch, tmp_path):
    created_workers: list[int] = []

    class FakeExecutor:
        def __init__(self, max_workers: int):
            created_workers.append(max_workers)

        def submit(self, fn, job):
            future: Future = Future()
            future.set_result(fn(job))
            return future

        def shutdown(self, wait=False, cancel_futures=False):
            return None

    monkeypatch.setenv("PAPER2MANIM_RENDER_WORKERS", "3")
    monkeypatch.setattr(parallel_renderer, "ProcessPoolExecutor", FakeExecutor)
    monkeypatch.setattr(
        parallel_renderer,
        "_render_single",
        lambda job: parallel_renderer.RenderResult(
            segment_id=job.segment_id,
            success=True,
            video_path=str(tmp_path / f"{job.segment_id}.mp4"),
        ),
    )

    parallel_renderer.reset_render_executor()
    job = parallel_renderer.RenderJob(segment_id=1, code="class Demo(Scene): pass", class_name="Demo")

    first = parallel_renderer.submit_render_job(job).result()
    second = parallel_renderer.render_parallel([job])[0]
    third = parallel_renderer.submit_render_job(job).result()

    assert first.success is True
    assert second.success is True
    assert third.success is True
    assert created_workers == [3]

    parallel_renderer.reset_render_executor()
