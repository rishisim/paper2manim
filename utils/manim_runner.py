import os
import subprocess
import tempfile
import json
import ast

def run_manim_code(code: str, class_name: str) -> dict:
    """
    Executes a Manim python script in a temporary directory and captures output.
    Returns a dict with 'success', 'video_path', and 'error' strings.
    """
    # Create a temporary directory for execution
    with tempfile.TemporaryDirectory() as temp_dir:
        # Write the code to a file
        script_path = os.path.join(temp_dir, "scene.py")
        with open(script_path, "w") as f:
            f.write(code)
            
        # The command to execute Manim
        # We use -qm for medium quality/speed. Add --format=mp4.
        cmd = ["manim", "-qm", "--media_dir", temp_dir, script_path, class_name]
        
        try:
            result = subprocess.run(cmd, cwd=temp_dir, capture_output=True, text=True, timeout=120)
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
                    # In a real app we need to copy this out of the temp dir before it gets deleted!
                    # For now just return path, but we'll copy it to a static output dir.
                    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "output"))
                    os.makedirs(output_dir, exist_ok=True)
                    final_path = os.path.join(output_dir, f"{class_name}.mp4")
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
