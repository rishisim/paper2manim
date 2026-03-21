import os
import subprocess
import tempfile
import json
import ast

def run_manim_code(code: str, class_name: str, quality_flag: str = "-ql", timeout_seconds: int = 120, output_dir: str | None = None) -> dict:
    """
    Executes a Manim python script in a temporary directory and captures output.
    Returns a dict with 'success', 'video_path', and 'error' strings.

    Args:
        output_dir: If provided, the rendered video is copied here instead of
                    the default ``output/`` directory.
    """
    # Create a temporary directory for execution
    with tempfile.TemporaryDirectory() as temp_dir:
        # Write the code to a file
        script_path = os.path.join(temp_dir, "scene.py")
        with open(script_path, "w") as f:
            f.write(code)
            
        # The command to execute Manim.
        # Fallback to env variables if not provided
        if not quality_flag:
            quality_flag = os.getenv("MANIM_QUALITY_FLAG", "-ql")
        if timeout_seconds <= 0:
            timeout_seconds = int(os.getenv("MANIM_RENDER_TIMEOUT_SECONDS", "120"))
            
        cmd = ["manim", quality_flag, "--media_dir", temp_dir, script_path, class_name]
        
        try:
            env = os.environ.copy()
            if "/Library/TeX/texbin" not in env.get("PATH", ""):
                env["PATH"] = f"/Library/TeX/texbin:{env.get('PATH', '')}"
                
            result = subprocess.run(
                cmd,
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
            if result.returncode == 0:
                # Find the generated mp4 video
                video_dir = os.path.join(temp_dir, "videos", "scene", "480p15") # -qm is 480p15 or 720p30 depending on version, let's just find the file
                # Better approach: search temp_dir for .mp4 files
                video_path = None
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        if file.endswith(f"{class_name}.mp4"):
                            video_path = os.path.join(root, file)
                            break
                            
                if video_path:
                    # Copy the rendered video to a persistent output directory
                    if output_dir:
                        dest_dir = os.path.abspath(output_dir)
                    else:
                        dest_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "output"))
                    os.makedirs(dest_dir, exist_ok=True)
                    final_path = os.path.join(dest_dir, f"{class_name}_render.mp4")
                    import shutil
                    shutil.copy2(video_path, final_path)
                    
                    return {"success": True, "video_path": final_path, "error": None}
                else:
                    return {"success": False, "video_path": None, "error": "Video file not found after successful execution.\n" + result.stdout}
            else:
                return {"success": False, "video_path": None, "error": result.stderr or result.stdout}
                
        except subprocess.TimeoutExpired as e:
            return {"success": False, "video_path": None, "error": f"Execution timed out: {e}"}
        except Exception as e:
            return {"success": False, "video_path": None, "error": str(e)}

def extract_class_name(code: str) -> str:
    """Extracts the first Manim Scene class name from the code."""
    try:
        tree = ast.parse(code)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                # Checking if it inherits from Scene or similar could be added here
                return node.name
    except SyntaxError:
        pass
    return "GeneratedScene"
