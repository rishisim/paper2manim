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
        "stages": {}
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
            if state:
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

