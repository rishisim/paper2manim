import streamlit as st
import os
from dotenv import load_dotenv

# Load env vars
load_dotenv()

from agents.planner import plan_video_concept
from agents.coder import run_coder_agent
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

    /* Hide code views when unchecked: look for the element containing .code-marker, and hide its next sibling (the expander) */
    .stApp:has(#css-toggle:not(:checked)) div[data-testid="stElementContainer"]:has(.code-marker) + div[data-testid="stElementContainer"],
    .stApp:has(#css-toggle:not(:checked)) .element-container:has(.code-marker) + .element-container { 
        display: none !important; 
    }
    
    /* Also hide the marker itself to prevent empty spacing */
    .stApp:has(#css-toggle:not(:checked)) div[data-testid="stElementContainer"]:has(.code-marker),
    .stApp:has(#css-toggle:not(:checked)) .element-container:has(.code-marker) { 
        display: none !important; 
    }

    /* Hide skeleton when checked */
    .stApp:has(#css-toggle:checked) div[data-testid="stElementContainer"]:has(.skeleton-view-container),
    .stApp:has(#css-toggle:checked) .element-container:has(.skeleton-view-container) { 
        display: none !important; 
    }
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
    generate_pressed = st.button(
        "Generate Video", type="primary", use_container_width=True
    )

if generate_pressed and concept:
    st.session_state.concept = concept

    with st.status("Generating video pipeline...", expanded=True) as status:
        with st.status("🧠 Researching and planning storyboard...") as plan_status:
            try:
                storyboard = plan_video_concept(concept)
            except Exception as exc:
                plan_status.update(label="❌ Storyboard planning failed", state="error")
                status.update(label="Failed", state="error", expanded=True)
                st.error("Could not generate a valid storyboard.")
                st.code(str(exc), language="text")
                st.stop()
            st.json(storyboard)
            plan_status.update(label="✅ Storyboard planned", state="complete")

        with st.status("🎙️ Generating voiceover...") as rtts_status:
            audio_path = os.path.join("output", "voiceover.wav")
            tts_result = generate_voiceover(storyboard["audio_script"], audio_path)
            if not tts_result.get("success"):
                rtts_status.update(
                    label="❌ Voiceover generation failed", state="error"
                )
                status.update(label="Failed", state="error", expanded=True)
                st.error("Voiceover generation failed.")
                if tts_result.get("error"):
                    with st.expander("Show Voiceover Error Logs"):
                        st.code(tts_result["error"], language="text")
                st.stop()
            audio_path = tts_result.get("audio_path", audio_path)
            st.audio(audio_path, format="audio/wav")
            rtts_status.update(label="✅ Voiceover generated", state="complete")

        with st.status("💻 Coding Manim script (Agentic Loop)...") as coder_status:
            # Render our custom HTML CSS-only toggle
            st.markdown(get_css_toggle(), unsafe_allow_html=True)

            coder_generator = run_coder_agent(storyboard["visual_instructions"])

            final_video_path = None
            current_code = ""

            # Always render the skeleton (CSS handles hiding it if toggle is checked)
            st.markdown(get_skeleton_html(), unsafe_allow_html=True)

            for update in coder_generator:
                st.write(f"**Step**: {update['status']}")

                if "error" in update and update["error"]:
                    with st.expander("Show Diagnostic Error Logs"):
                        st.code(update["error"], language="bash")

                if "code" in update:
                    current_code = update["code"]
                    # Add our hidden marker right before the code expander
                    st.markdown(
                        "<div class='code-marker' style='display:none;'></div>",
                        unsafe_allow_html=True,
                    )
                    # Create the actual code expander
                    with st.expander("View Code Written So Far", expanded=False):
                        st.code(current_code, language="python")

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
                stitch_result = stitch_video_and_audio(
                    final_video_path, audio_path, final_output
                )

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
