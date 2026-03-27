import os
import re
import shutil
import subprocess
import sys
import tempfile
import json
import ast


def _find_manim_binary() -> str:
    """Return the manim executable path, falling back through venv and sys.executable."""
    manim_bin = shutil.which("manim")
    if not manim_bin:
        venv_bin = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".venv", "bin", "manim",
        )
        if os.path.isfile(venv_bin):
            manim_bin = venv_bin
        else:
            manim_bin = os.path.join(os.path.dirname(sys.executable), "manim")
            if not os.path.isfile(manim_bin):
                manim_bin = "manim"
    return manim_bin


def _make_manim_env() -> dict:
    """Return os.environ copy with TeX binaries prepended to PATH.

    Checks a platform-agnostic list of candidate directories for pdflatex
    and prepends whichever ones are found — works on macOS, Linux, and Windows.
    """
    # M14: Cross-platform TeX PATH detection instead of hardcoded macOS path
    tex_candidates = [
        "/Library/TeX/texbin",               # macOS MacTeX
        "/usr/local/texlive/bin/universal-darwin",  # macOS alternate TeX Live
        "/opt/homebrew/bin",                  # Homebrew (Apple Silicon)
        "/usr/local/bin",                     # Homebrew (Intel) / Linux
        "/usr/bin",                           # Linux system TeX
    ]
    env = os.environ.copy()
    current_path = env.get("PATH", "")
    to_prepend = [
        d for d in tex_candidates
        if d not in current_path and os.path.isfile(os.path.join(d, "pdflatex"))
    ]
    if to_prepend:
        env["PATH"] = ":".join(to_prepend) + ":" + current_path
    return env


def _default_timeout_for_quality(quality_flag: str) -> int:
    """Return a quality-aware default timeout in seconds."""
    flag = (quality_flag or "").strip()
    if flag in {"-ql", "--quality", "l", "low_quality"}:
        return int(os.getenv("MANIM_RENDER_TIMEOUT_LOW_SECONDS", "45"))
    if flag in {"-qm", "m", "medium_quality"}:
        return int(os.getenv("MANIM_RENDER_TIMEOUT_MEDIUM_SECONDS", "90"))
    if flag in {"-qh", "h", "high_quality"}:
        return int(os.getenv("MANIM_RENDER_TIMEOUT_HIGH_SECONDS", "240"))
    return int(os.getenv("MANIM_RENDER_TIMEOUT_SECONDS", "120"))

def dry_run_manim_code(code: str, class_name: str, timeout_seconds: int = 0) -> dict:
    """Validate a Manim scene using --dry_run (no rendering).

    Executes ``construct()`` without producing any video, catching Python
    runtime errors, Manim API misuse, and LaTeX compilation failures in
    ~5-10s instead of the 45-240s a full render requires.

    Returns the same shape as ``run_manim_code``, always with
    ``video_path=None`` on success.
    """
    if timeout_seconds <= 0:
        timeout_seconds = int(os.getenv("MANIM_DRY_RUN_TIMEOUT_SECONDS", "30"))

    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = os.path.join(temp_dir, "scene.py")
        with open(script_path, "w") as f:
            f.write(code)

        cmd = [_find_manim_binary(), "--dry_run", "--media_dir", temp_dir, script_path, class_name]

        try:
            env = _make_manim_env()

            result = subprocess.run(
                cmd,
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )

            if result.returncode == 0:
                return {"success": True, "video_path": None, "error": None}

            stderr = result.stderr or ""
            # If --dry_run is unrecognised (old Manim version), treat as a pass
            # so the pipeline continues to the HD render which will surface errors.
            if "dry_run" in stderr and (
                "unrecognized" in stderr.lower() or "no such option" in stderr.lower()
            ):
                return {
                    "success": True,
                    "video_path": None,
                    "error": None,
                    "dry_run_unsupported": True,
                }

            return {"success": False, "video_path": None, "error": stderr or result.stdout}

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "video_path": None,
                "error": (
                    f"Dry run timed out after {timeout_seconds}s. "
                    "Scene likely contains infinite loops or extremely expensive "
                    "object construction. Simplify geometry and remove costly updaters."
                ),
                "error_type": "timeout",
            }
        except Exception as e:
            return {"success": False, "video_path": None, "error": str(e)}


def run_manim_code(code: str, class_name: str, quality_flag: str = "-ql", timeout_seconds: int = 0, output_dir: str | None = None) -> dict:
    """
    Executes a Manim python script in a temporary directory and captures output.
    Returns a dict with 'success', 'video_path', and 'error' strings.

    Args:
        output_dir: If provided, the rendered video is copied here instead of
                    the default ``output/`` directory.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = os.path.join(temp_dir, "scene.py")
        with open(script_path, "w") as f:
            f.write(code)

        if not quality_flag:
            quality_flag = os.getenv("MANIM_QUALITY_FLAG", "-ql")
        if timeout_seconds <= 0:
            timeout_seconds = _default_timeout_for_quality(quality_flag)

        cmd = [_find_manim_binary(), quality_flag, "--media_dir", temp_dir, script_path, class_name]

        try:
            env = _make_manim_env()
                
            result = subprocess.run(
                cmd,
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
            if result.returncode == 0:
                video_path = None
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        if file.endswith(f"{class_name}.mp4"):
                            video_path = os.path.join(root, file)
                            break
                            
                if video_path:
                    if output_dir:
                        dest_dir = os.path.abspath(output_dir)
                    else:
                        dest_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "output"))
                    os.makedirs(dest_dir, exist_ok=True)
                    final_path = os.path.join(dest_dir, f"{class_name}_render.mp4")
                    shutil.copy2(video_path, final_path)
                    
                    return {"success": True, "video_path": final_path, "error": None}
                else:
                    return {"success": False, "video_path": None, "error": "Video file not found after successful execution.\n" + result.stdout}
            else:
                return {"success": False, "video_path": None, "error": result.stderr or result.stdout}
                
        except subprocess.TimeoutExpired as e:
            return {
                "success": False,
                "video_path": None,
                "error": (
                    "Execution timed out after "
                    f"{timeout_seconds}s at quality {quality_flag}. "
                    "Likely causes: computationally expensive geometry, large always_redraw trees, "
                    "or long-running updaters. Simplify the scene and reduce object count."
                ),
                "error_type": "timeout",
                "timeout_seconds": timeout_seconds,
                "quality_flag": quality_flag,
            }
        except Exception as e:
            return {"success": False, "video_path": None, "error": str(e)}

def extract_class_name(code: str) -> str:
    """Extracts the Manim Scene class name from the code.

    Prefers classes that inherit from a known Scene base (Scene, ThreeDScene, etc.)
    over arbitrary helper classes. Falls back to the first class found, then to
    'GeneratedScene' if the code cannot be parsed.
    """
    try:
        tree = ast.parse(code)
        scene_classes: list[str] = []
        other_classes: list[str] = []
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            is_scene = any(
                (isinstance(b, ast.Name) and b.id in _SCENE_BASES)
                or (isinstance(b, ast.Attribute) and b.attr in _SCENE_BASES)
                for b in node.bases
            )
            (scene_classes if is_scene else other_classes).append(node.name)
        if scene_classes:
            return scene_classes[0]
        if other_classes:
            return other_classes[0]
    except SyntaxError:
        pass
    return "GeneratedScene"


_ALLOWED_IMPORTS = {
    "manim", "numpy", "np", "math", "itertools", "functools",
    "collections", "typing", "dataclasses", "random", "enum",
    "copy", "operator", "string", "textwrap",
}

_SCENE_BASES = {
    "Scene", "ThreeDScene", "MovingCameraScene", "ZoomedScene",
    "LinearTransformationScene",
}

_SINGLE_BACKSLASH_RE = re.compile(
    r'(?<!\\)\\(frac|int|sum|vec|text|sqrt|alpha|beta|gamma|theta|pi|infty|'
    r'cdot|times|left|right|begin|end|partial|nabla|delta|epsilon|sigma|omega|'
    r'lambda|mu|phi|psi|rho|tau|chi|zeta|eta|kappa|xi|hat|bar|dot|tilde|'
    r'mathrm|mathbf|mathbb|mathcal|operatorname)\b'
)


def validate_manim_code(code: str) -> dict:
    """Pre-execution validation of generated Manim code.

    Returns {"errors": [...], "warnings": [...]}.
    Errors are hard blockers (syntax, imports, missing Scene class).
    Warnings are advisory (LaTeX hints).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1. AST syntax check
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        errors.append(f"SyntaxError: {e.msg} (line {e.lineno})")
        return {"errors": errors, "warnings": warnings}

    # 2. Import allowlist check
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in _ALLOWED_IMPORTS:
                    errors.append(
                        f"Disallowed import '{alias.name}' at line {node.lineno}. "
                        f"Only manim, numpy, and stdlib imports are allowed."
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top not in _ALLOWED_IMPORTS:
                    errors.append(
                        f"Disallowed import 'from {node.module}' at line {node.lineno}. "
                        f"Only manim, numpy, and stdlib imports are allowed."
                    )

    # 3. Scene class presence check
    has_scene = False
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                base_name = ""
                if isinstance(base, ast.Name):
                    base_name = base.id
                elif isinstance(base, ast.Attribute):
                    base_name = base.attr
                if base_name in _SCENE_BASES:
                    has_scene = True
                    break
            if has_scene:
                break
    if not has_scene:
        errors.append(
            "No Scene subclass found. Code must define a class inheriting from "
            "Scene, ThreeDScene, MovingCameraScene, or similar."
        )

    # 4. Single-backslash LaTeX heuristic (warning only)
    matches = _SINGLE_BACKSLASH_RE.findall(code)
    if matches:
        unique = sorted(set(matches))[:5]
        warnings.append(
            f"Possible single-backslash LaTeX commands detected: "
            f"{', '.join('\\\\' + m for m in unique)}. "
            f"Use double backslashes (e.g. \\\\frac, \\\\int) in raw strings."
        )

    return {"errors": errors, "warnings": warnings}
