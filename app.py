import streamlit as st
import os
import html
from dotenv import load_dotenv

# Load env vars
load_dotenv()

from agents.planner import plan_video_concept
from agents.coder import run_coder_agent
from agents.pipeline import run_segmented_pipeline
from utils.tts_engine import generate_voiceover
from utils.media_assembler import stitch_video_and_audio

st.set_page_config(page_title="Paper2Manim Studio", layout="wide", page_icon="🎬")

# --- Header Section ---
st.markdown(
    "<h1 style='text-align: center;'>🎬 Paper2Manim Studio</h1>", unsafe_allow_html=True
)
st.markdown(
    "<p style='text-align: center; color: #666;'>Generate beautiful 3Blue1Brown-style educational videos from simple concepts using LLMs, Manim, and self-correcting agents.</p>",
    unsafe_allow_html=True,
)
st.divider()

# Check API key
if not os.getenv("GEMINI_API_KEY"):
    st.error(
        "Please set your GEMINI_API_KEY environment variable (e.g. in a .env file)."
    )
    st.info(
        "Create a `.env` file in the root directory and add `GEMINI_API_KEY=your_key_here`"
    )
    st.stop()

# Ensure output directory exists
os.makedirs("output", exist_ok=True)

# State initialization
if "concept" not in st.session_state:
    st.session_state.concept = ""


def get_css_toggle():
    return """
    <style>
    /* Toggle behavior */
    .stApp:has(#css-toggle:not(:checked)) .code-view-container {
        display: none !important;
    }
    .stApp:has(#css-toggle:checked) .skeleton-view-container {
        display: none !important;
    }

    /* Toggle switch */
    .switch-wrapper {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 15px;
        font-family: sans-serif;
        font-size: 14px;
        color: #666;
    }
    .switch {
      position: relative;
      display: inline-block;
      width: 36px;
      height: 20px;
    }
    .switch input { opacity: 0; width: 0; height: 0; }
    .slider {
      position: absolute;
      cursor: pointer;
      top: 0; left: 0; right: 0; bottom: 0;
      background-color: #ccc;
      transition: .4s;
      border-radius: 20px;
    }
    .slider:before {
      position: absolute;
      content: "";
      height: 16px;
      width: 16px;
      left: 2px;
      bottom: 2px;
      background-color: white;
      transition: .4s;
      border-radius: 50%;
    }
    input:checked + .slider { background-color: #FF4B4B; }
    input:checked + .slider:before { transform: translateX(16px); }
    </style>
    <div class="switch-wrapper">
        <label class="switch">
          <input type="checkbox" id="css-toggle" checked>
          <span class="slider"></span>
        </label>
        <span><b>Show real-time code changes</b></span>
    </div>
    """


def get_skeleton_html():
    return """
    <style>
    .skeleton {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: rgba(169, 169, 169, 0.05);
    }
    .skeleton-text {
        height: 1.2rem;
        margin-bottom: 0.6rem;
        border-radius: 0.25rem;
        animation: skeleton-loading 1.2s ease-in-out infinite alternate;
    }
    @keyframes skeleton-loading {
        0% { background-color: rgba(169, 169, 169, 0.2); }
        100% { background-color: rgba(169, 169, 169, 0.5); }
    }
    </style>
    <div class="skeleton-view-container skeleton">
      <div class="skeleton-text" style="width: 40%;"></div>
      <div class="skeleton-text" style="width: 70%;"></div>
      <div class="skeleton-text" style="width: 90%;"></div>
      <div class="skeleton-text" style="width: 60%;"></div>
      <div class="skeleton-text" style="width: 80%;"></div>
      <div class="skeleton-text" style="width: 50%;"></div>
    </div>
    """


def get_code_view_html(code: str) -> str:
    safe_code = html.escape(code)
    return f"""
    <style>
    .code-view-container {{
        border: 1px solid rgba(49, 51, 63, 0.2);
        border-radius: 0.5rem;
        overflow: hidden;
    }}
    .code-view-header {{
        font-size: 0.85rem;
        font-weight: 600;
        color: #666;
        background: rgba(169, 169, 169, 0.06);
        padding: 0.5rem 0.75rem;
        border-bottom: 1px solid rgba(49, 51, 63, 0.1);
    }}
    .code-view-container pre {{
        margin: 0;
        padding: 0.85rem;
        max-height: 420px;
        overflow: auto;
        white-space: pre;
        font-family: "Source Code Pro", Menlo, Monaco, Consolas, "Courier New", monospace;
        font-size: 0.83rem;
        line-height: 1.35;
        background: rgba(249, 250, 251, 0.7);
    }}
    </style>
    <div class="code-view-container">
      <div class="code-view-header">Live Manim Script</div>
      <pre><code>{safe_code}</code></pre>
    </div>
    """


# --- Input Section ---
with st.container():
    st.markdown("### What would you like to visualize?")

    concept = st.text_input(
        "Concept or Topic:",
        value=st.session_state.concept,
        placeholder="e.g. The Chain Rule, Quicksort Algorithm, etc.",
        label_visibility="collapsed",
    )

    st.markdown("**Suggested Prompts:**")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("📐 Visualize Dot Products", use_container_width=True):
            st.session_state.concept = "Linear Algebra: Dot Products"
            st.rerun()
    with col2:
        if st.button("📐 The Pythagorean Theorem", use_container_width=True):
            st.session_state.concept = "The Pythagorean Theorem"
            st.rerun()
    with col3:
        if st.button("📈 Explain the Chain Rule", use_container_width=True):
            st.session_state.concept = "Calculus: The Chain Rule"
            st.rerun()

    st.write("")  # Spacer
    col_mode1, col_mode2 = st.columns(2)
    with col_mode1:
        use_segmented = st.toggle("⚡ Segmented Pipeline (parallel)", value=True,
                                   help="Break the video into segments and generate them in parallel. Much faster for longer videos.")
    with col_mode2:
        pass

    generate_pressed = st.button(
        "Generate Video", type="primary", use_container_width=True
    )

if generate_pressed and concept:
    st.session_state.concept = concept

    if use_segmented:
        # ── Segmented parallel pipeline ───────────────────────────────
        with st.status("⚡ Running segmented pipeline...", expanded=True) as status:
            pipeline = run_segmented_pipeline(concept)
            
            storyboard_data = None
            final_video_path = None
            num_segments = 0
            
            # Create placeholders for live updates
            stage_placeholder = st.empty()
            detail_placeholder = st.empty()
            progress_placeholder = st.empty()
            
            stage_labels = {
                "plan": "🧠 Planning",
                "tts": "🎙️ Voiceovers",
                "code": "💻 Coding",
                "stitch": "🎬 Stitching",
                "concat": "🔗 Concatenating",
                "done": "✅ Complete",
            }
            
            for update in pipeline:
                stage = update.get("stage", "")
                stage_label = stage_labels.get(stage, stage)
                update_status = update.get("status", "")
                
                stage_placeholder.markdown(f"**{stage_label}**: {update_status}")
                
                # Show storyboard when planned
                if "storyboard" in update:
                    storyboard_data = update["storyboard"]
                    num_segments = update.get("num_segments", 0)
                    with detail_placeholder.container():
                        st.json(storyboard_data)
                        if storyboard_data.get("clarifying_questions"):
                            st.warning("The planner has some clarifying questions:")
                            for q in storyboard_data["clarifying_questions"]:
                                st.write(f"- {q}")
                
                # Show TTS results
                if "tts_results" in update:
                    tts_results = update["tts_results"]
                    ok = sum(1 for r in tts_results.values() if r.get("success"))
                    progress_placeholder.progress(ok / max(num_segments, 1),
                                                   text=f"TTS: {ok}/{num_segments}")
                
                # Show code results
                if "code_results" in update:
                    code_results = update["code_results"]
                    ok = sum(1 for r in code_results.values() if r.get("video_path"))
                    progress_placeholder.progress(ok / max(num_segments, 1),
                                                   text=f"Segments rendered: {ok}/{num_segments}")
                
                # Show errors
                if "error" in update and update["error"] and not update.get("final"):
                    with st.expander(f"⚠️ Error in {stage_label}"):
                        st.code(update["error"], language="text")
                
                # Final result
                if update.get("final"):
                    final_video_path = update.get("video_path")
                    
                    if update.get("stitch_errors"):
                        with st.expander("⚠️ Stitch warnings"):
                            for e in update["stitch_errors"]:
                                st.write(f"- {e}")
                    
                    if final_video_path:
                        status.update(
                            label=f"🎉 Video generation complete! ({num_segments} segments)",
                            state="complete",
                            expanded=False,
                        )
                        st.success(f"Successfully generated {num_segments}-segment video!")
                        st.video(final_video_path)
                    else:
                        status.update(label="❌ Pipeline failed", state="error", expanded=True)
                        st.error(f"Pipeline failed: {update.get('error', 'Unknown error')}")

    else:
        # ── Legacy single-segment pipeline ────────────────────────────
        _run_legacy_pipeline(concept)


def _run_legacy_pipeline(concept: str):
    """Original single-segment pipeline (kept for backward compatibility)."""
    with st.status("Generating video pipeline...", expanded=True) as status:
        with st.status("🧠 Researching and planning storyboard...") as plan_status:
            try:
                storyboard_generator = plan_video_concept(concept)
                storyboard = None
                for update in storyboard_generator:
                    if "status" in update:
                        plan_status.update(label=f"🧠 {update['status']}", state="running")
                    if update.get("final"):
                        if "error" in update:
                            raise Exception(update["error"])
                        storyboard = update.get("storyboard")
            except Exception as exc:
                plan_status.update(label="❌ Storyboard planning failed", state="error")
                status.update(label="Failed", state="error", expanded=True)
                st.error("Could not generate a valid storyboard.")
                st.code(str(exc), language="text")
                st.stop()
            st.json(storyboard)
            if storyboard.get("clarifying_questions"):
                st.warning("The planner has some clarifying questions:")
                for q in storyboard["clarifying_questions"]:
                    st.write(f"- {q}")
                st.info("You can stop here and adjust your prompt, or continue if you're happy with the current plan.")
            plan_status.update(label="✅ Storyboard planned", state="complete")

        with st.status("🎙️ Generating voiceover...") as rtts_status:
            audio_path = os.path.join("output", "voiceover.wav")

            tts_generator = generate_voiceover(storyboard["audio_script"], audio_path)
            tts_result = None
            for update in tts_generator:
                if "status" in update:
                    rtts_status.update(label=f"🎙️ {update['status']}", state="running")
                if update.get("final"):
                    tts_result = update

            if not tts_result or not tts_result.get("success"):
                rtts_status.update(
                    label="❌ Voiceover generation failed", state="error"
                )
                status.update(label="Failed", state="error", expanded=True)
                st.error("Voiceover generation failed.")
                if tts_result and tts_result.get("error"):
                    with st.expander("Show Voiceover Error Logs"):
                        st.code(tts_result["error"], language="text")
                st.stop()
            audio_path = tts_result.get("audio_path", audio_path)
            audio_duration = tts_result.get("duration", 0.0)

        with st.status("💻 Coding Manim script (Agentic Loop)...") as coder_status:
            st.markdown(get_css_toggle(), unsafe_allow_html=True)

            coder_generator = run_coder_agent(
                storyboard["visual_instructions"],
                audio_script=storyboard.get("audio_script", ""),
                audio_duration=audio_duration,
            )

            final_video_path = None
            current_code = ""
            last_status = None
            status_placeholder = st.empty()
            error_placeholder = st.empty()
            code_placeholder = st.empty()

            st.markdown(get_skeleton_html(), unsafe_allow_html=True)

            for update in coder_generator:
                if update["status"] != last_status:
                    status_placeholder.markdown(f"**Step**: {update['status']}")
                    last_status = update["status"]

                if "error" in update and update["error"]:
                    with error_placeholder.container():
                        with st.expander("Show Diagnostic Error Logs"):
                            st.code(update["error"], language="bash")

                if "code" in update:
                    current_code = update["code"]
                    code_placeholder.markdown(
                        get_code_view_html(current_code), unsafe_allow_html=True
                    )

                if update.get("final"):
                    final_video_path = update.get("video_path")
                    if not final_video_path:
                        coder_status.update(label="❌ Generation failed", state="error")
                        status.update(label="Failed", state="error", expanded=True)
                        st.stop()

            coder_status.update(
                label="✅ Manim script generated and verified", state="complete"
            )

        if final_video_path:
            with st.status("🎬 Stitching audio and video...") as stitch_status:
                final_output = os.path.join("output", "final_output.mp4")
                stitch_generator = stitch_video_and_audio(
                    final_video_path, audio_path, final_output
                )

                stitch_result = None
                for update in stitch_generator:
                    if "status" in update:
                        stitch_status.update(label=f"🎬 {update['status']}", state="running")
                    if update.get("final"):
                        stitch_result = update

                if stitch_result.get("success"):
                    stitch_status.update(
                        label="✅ Audio and video stitched", state="complete"
                    )
                    status.update(
                        label="🎉 Video generation complete!",
                        state="complete",
                        expanded=False,
                    )
                    st.success("Successfully generated!")
                    st.video(final_output)
                else:
                    stitch_status.update(
                        label="⚠️ Failed to stitch audio/video", state="error"
                    )
                    status.update(
                        label="Video generation complete (no audio)",
                        state="complete",
                        expanded=False,
                    )
                    st.warning(
                        "Failed to stitch audio and video. You can view the raw animation below:"
                    )
                    if stitch_result.get("error"):
                        with st.expander("Show Stitching Error Logs"):
                            st.code(stitch_result["error"], language="text")
                    st.video(final_video_path)
