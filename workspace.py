import streamlit as st
import os

from utils.project_state import list_all_projects, delete_project

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
        total_segments = state.get("total_segments", 1)
        stages = state.get("stages", {})
        status = state.get("status", "in_progress")
        
        # Calculate rough progress safely
        completed_stages = sum(1 for s in stages.values() if s.get("done", False))
        # Approximate total stages: outline + (storyboard + tts + code + stitch) per segment + concat
        approx_total_stages = 1 + (4 * total_segments) + (1 if total_segments > 1 else 0)
        progress = min(1.0, completed_stages / max(1, approx_total_stages)) if status != "completed" else 1.0

        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.subheader(f"{concept}")
                st.caption(f"Last updated: {updated_at}")
                st.progress(progress, text=f"Progress: {int(progress * 100)}%")
                
            with col2:
                st.markdown("<br>", unsafe_allow_html=True)
                if status == "completed":
                    st.success("Completed 🎉")
                    # If there's a final concatenated video, show a link to it
                    slug = state.get("slug", "video")
                    final_vid = os.path.join(project_dir, f"{slug}.mp4")
                    if os.path.exists(final_vid):
                         # Streamlit download button or abstract just the success state
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

