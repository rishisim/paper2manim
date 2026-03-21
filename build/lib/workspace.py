import streamlit as st
import os

from utils.project_state import list_all_projects, delete_project, calculate_progress


def _read_pipeline_summary(project_dir: str) -> str | None:
    summary_path = os.path.join(project_dir, "pipeline_summary.txt")
    if not os.path.exists(summary_path):
        return None
    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def render_workspace():
    st.markdown("## 🗂️ Project Workspace")
    st.markdown("Resume or delete existing video projects.")
    
    projects = list_all_projects("output")
    
    if not projects:
        st.info("No projects found in the workspace yet. Start generating a video to see it here!")
        return

    for project_dir, state in projects:
        concept = state.get("concept", "Unknown Concept")
        created_at = state.get("created_at", "Unknown Date")
        updated_at = state.get("updated_at", "Unknown Date")
        status = state.get("status", "in_progress")
        
        done, total, desc = calculate_progress(state)
        progress = min(1.0, done / max(1, total))

        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.subheader(f"{concept}")
                st.caption(f"Last updated: {updated_at}")
                st.progress(progress, text=f"Progress: {int(progress * 100)}% — {desc}")

                summary = _read_pipeline_summary(project_dir)
                with st.expander("ℹ️ Pipeline summary", expanded=False):
                    if summary:
                        st.text(summary)
                    else:
                        st.caption("No pipeline summary available yet.")
                
            with col2:
                st.markdown("<br>", unsafe_allow_html=True)
                if status == "completed":
                    st.success("Completed 🎉")
                    # If there's a final concatenated video, show a link to it
                    slug = state.get("slug", "video")
                    final_vid = os.path.join(project_dir, f"{slug}.mp4")
                    if os.path.exists(final_vid):
                         if st.button("Download / View Video", key=f"dl_{project_dir}", use_container_width=True):
                             st.session_state.current_video_to_view = final_vid
                             st.rerun()
                else:
                    if st.button("▶ Resume", key=f"resume_{project_dir}", type="primary", use_container_width=True):
                        st.session_state.resume_project_dir = project_dir
                        st.session_state.concept = concept
                        st.rerun()
                        
                if st.button("🗑️ Delete", key=f"delete_{project_dir}", use_container_width=True):
                    if delete_project(project_dir):
                        st.rerun()
                    else:
                        st.error("Failed to delete project directory.")

