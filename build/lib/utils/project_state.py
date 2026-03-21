import json
import os
import time
from typing import Any, Optional


def _get_state_path(output_dir: str) -> str:
    return os.path.join(output_dir, "project_state.json")


def create_project(output_dir: str, concept: str, concept_slug: str, total_segments: int = 1) -> dict[str, Any]:
    """Creates a new project state file in the output directory."""
    os.makedirs(output_dir, exist_ok=True)
    
    # Initialize default state structure
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    state = {
        "concept": concept,
        "slug": concept_slug,
        "created_at": now,
        "updated_at": now,
        "status": "in_progress",
        "total_segments": total_segments,
        "stages": {},
        "segments": {},  # per-segment tracking
    }
    
    save_project(output_dir, state)
    return state


def load_project(output_dir: str) -> dict[str, Any]:
    """Loads the project state if it exists, otherwise returns None."""
    state_path = _get_state_path(output_dir)
    if not os.path.exists(state_path):
        return None
        
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return None


def save_project(output_dir: str, state: dict[str, Any]) -> None:
    """Saves the project state to disk."""
    state_path = _get_state_path(output_dir)
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def mark_stage_done(output_dir: str, stage_name: str, artifacts: list[str] = None) -> dict[str, Any]:
    """Marks a specific stage as completed and saves the state."""
    state = load_project(output_dir)
    if not state:
        raise ValueError(f"No project state found in {output_dir}")
        
    state["stages"][stage_name] = {
        "done": True,
        "artifacts": artifacts or []
    }
    save_project(output_dir, state)
    return state


# ── Per-segment stage tracking ────────────────────────────────────────

def mark_segment_stage(
    output_dir: str,
    segment_id: int,
    stage: str,
    done: bool = True,
    artifacts: list[str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Mark a per-segment stage (tts, code, render, stitch) as done/failed.

    State structure:
        ``state["segments"]["1"]["tts"] = {"done": True, "artifacts": [...]}``
    """
    state = load_project(output_dir)
    if not state:
        raise ValueError(f"No project state found in {output_dir}")

    seg_key = str(segment_id)
    if "segments" not in state:
        state["segments"] = {}
    if seg_key not in state["segments"]:
        state["segments"][seg_key] = {}

    entry: dict[str, Any] = {"done": done}
    if artifacts:
        entry["artifacts"] = artifacts
    if error:
        entry["error"] = error

    state["segments"][seg_key][stage] = entry
    save_project(output_dir, state)
    return state


def is_segment_stage_done(state: dict[str, Any], segment_id: int, stage: str) -> bool:
    """Check whether a specific segment stage has completed successfully."""
    seg_key = str(segment_id)
    seg = state.get("segments", {}).get(seg_key, {})
    return seg.get(stage, {}).get("done", False)


def get_segment_progress(state: dict[str, Any]) -> dict[str, dict]:
    """Return a summary of per-segment progress.

    Returns:
        ``{segment_id: {"tts": bool, "code": bool, "render": bool, "stitch": bool}}``
    """
    result = {}
    for seg_key, stages in state.get("segments", {}).items():
        result[seg_key] = {
            stage: info.get("done", False) for stage, info in stages.items()
        }
    return result

def mark_project_complete(output_dir: str) -> dict[str, Any]:
    state = load_project(output_dir)
    if not state:
        raise ValueError(f"No project state found in {output_dir}")
    
    state["status"] = "completed"
    save_project(output_dir, state)
    return state

def is_stage_done(state: dict[str, Any], stage_name: str) -> bool:
    """Checks if a stage is marked as done in the state."""
    if not state or "stages" not in state:
        return False
    stage_info = state["stages"].get(stage_name, {})
    return stage_info.get("done", False)


def calculate_progress(state: dict[str, Any]) -> tuple[int, int, str]:
    """Calculate overall project progress from state.

    Handles both single-segment CLI projects (top-level stages only) and
    segmented pipeline projects (top-level stages + per-segment stages).

    Returns:
        ``(done_count, total_count, description)``
    """
    if not state:
        return 0, 1, "Unknown"

    if state.get("status") == "completed":
        return 1, 1, "Completed"

    stages = state.get("stages", {})
    segments = state.get("segments", {})
    total_segments = state.get("total_segments", 1)

    # Detect segmented pipeline: has per-segment tracking or total_segments > 1
    is_segmented = total_segments > 1 or len(segments) > 0

    if is_segmented:
        # Segmented pipeline stages:
        #   top-level: plan (1) + concat (1)
        #   per-segment: tts, code, render, stitch (4 each)
        total = 1 + (4 * total_segments) + 1  # plan + per-seg + concat
        done = 0

        # Top-level stages (count only canonical stages)
        if stages.get("plan", {}).get("done"):
            done += 1
        if stages.get("concat", {}).get("done"):
            done += 1

        # Per-segment stages (count canonical stage set only)
        for seg_stages in segments.values():
            if not isinstance(seg_stages, dict):
                continue

            if seg_stages.get("tts", {}).get("done"):
                done += 1
            if seg_stages.get("code", {}).get("done"):
                done += 1

            # Treat either render or hd_render as the render milestone.
            if seg_stages.get("render", {}).get("done") or seg_stages.get("hd_render", {}).get("done"):
                done += 1

            if seg_stages.get("stitch", {}).get("done"):
                done += 1

        # Build description
        if done == 0:
            desc = "Starting"
        elif is_stage_done(state, "plan") and done <= 1:
            desc = "Planned"
        elif done < 1 + (4 * total_segments):
            desc = "Generating segments"
        elif done < total:
            desc = "Stitching"
        else:
            desc = "Almost done"

        return done, total, desc
    else:
        # CLI single-segment: plan, voiceover, code, stitch (4 stages)
        total = 4
        done = sum(1 for s in stages.values() if s.get("done"))

        if done == 0:
            desc = "Starting"
        elif done == 1:
            desc = "Planned"
        elif done == 2:
            desc = "Voice generated"
        elif done == 3:
            desc = "Code rendered"
        else:
            desc = "Stitching"

        return done, total, desc


def _is_placeholder_project(output_dir: str, state: dict[str, Any]) -> bool:
    """Detect stale/ghost project entries with no real pipeline activity.

    These were previously created before pipeline execution, then abandoned.
    """
    if not state:
        return True

    if state.get("status") == "completed":
        return False

    if state.get("stages") or state.get("segments"):
        return False

    try:
        for name in os.listdir(output_dir):
            if name == "project_state.json":
                continue
            # Any other artifact indicates this is not a placeholder.
            return False
    except Exception:
        return False

    return True


def list_placeholder_projects(base_dir: str = "output") -> list[str]:
    """Return project directories that are placeholders/stale entries."""
    if not os.path.exists(base_dir):
        return []

    placeholders: list[str] = []
    for d in os.listdir(base_dir):
        full_dir = os.path.join(base_dir, d)
        if not os.path.isdir(full_dir):
            continue
        state = load_project(full_dir)
        if state and _is_placeholder_project(full_dir, state):
            placeholders.append(full_dir)

    placeholders.sort()
    return placeholders


def cleanup_placeholder_projects(base_dir: str = "output") -> int:
    """Delete placeholder/stale project directories and return removed count."""
    import shutil

    removed = 0
    for project_dir in list_placeholder_projects(base_dir):
        try:
            shutil.rmtree(project_dir)
            removed += 1
        except Exception:
            continue
    return removed


def list_all_projects(base_dir: str = "output") -> list[tuple[str, dict[str, Any]]]:
    """
    Scans the base directory for all projects containing a project_state.json.
    Returns a list of tuples: (project_dir_path, state_dict).
    """
    if not os.path.exists(base_dir):
        return []
        
    projects = []
    # Only scan immediate subdirectories
    for d in os.listdir(base_dir):
        full_dir = os.path.join(base_dir, d)
        if os.path.isdir(full_dir):
            state = load_project(full_dir)
            if state and not _is_placeholder_project(full_dir, state):
                projects.append((full_dir, state))
                
    # Sort by updated_at descending (newest first)
    projects.sort(key=lambda x: x[1].get("updated_at", ""), reverse=True)
    return projects

def delete_project(output_dir: str) -> bool:
    import shutil
    if os.path.exists(output_dir):
        try:
            shutil.rmtree(output_dir)
            return True
        except Exception:
            return False
    return False

