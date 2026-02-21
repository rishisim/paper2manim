import streamlit as st
import os
from dotenv import load_dotenv

# Load env vars
load_dotenv()

from agents.planner import plan_video_concept
from agents.coder import run_coder_agent
from utils.tts_engine import generate_voiceover
from utils.media_assembler import stitch_video_and_audio

st.set_page_config(page_title="Agentic Manim Studio", layout="wide")

st.title("🎬 Agentic Manim Studio")
st.markdown("Generate 3Blue1Brown-style educational videos from simple concepts using LLMs, Manim, and self-correcting agents.")

# Check API key
if not os.getenv("GEMINI_API_KEY"):
    st.error("Please set your GEMINI_API_KEY environment variable (e.g. in a .env file).")
    st.info("Create a `.env` file in the root directory and add `GEMINI_API_KEY=your_key_here`")
    st.stop()

# Ensure output directory exists
os.makedirs("output", exist_ok=True)

# State initialization
if "concept" not in st.session_state:
    st.session_state.concept = ""

# Suggested prompts
st.markdown("### Suggested Prompts")
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("Visualize Dot Products"):
        st.session_state.concept = "Linear Algebra: Dot Products"
with col2:
    if st.button("The Pythagorean Theorem"):
        st.session_state.concept = "The Pythagorean Theorem"
with col3:
    if st.button("Explain the Chain Rule"):
        st.session_state.concept = "Calculus: The Chain Rule"

concept = st.text_input("Concept or Topic:", value=st.session_state.concept)

if st.button("Generate Video", type="primary") and concept:
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
                rtts_status.update(label="❌ Voiceover generation failed", state="error")
                status.update(label="Failed", state="error", expanded=True)
                st.error("Voiceover generation failed.")
                if tts_result.get("error"):
                    with st.expander("Show Voiceover Error Logs"):
                        st.code(tts_result["error"], language="text")
                st.stop()
            audio_path = tts_result.get("audio_path", audio_path)
            rtts_status.update(label="✅ Voiceover generated", state="complete")

        with st.status("💻 Coding Manim script (Agentic Loop)...") as coder_status:
            coder_generator = run_coder_agent(storyboard["visual_instructions"])

            final_video_path = None
            current_code = ""

            for update in coder_generator:
                st.write(f"**Step**: {update['status']}")

                if "error" in update and update["error"]:
                    with st.expander("Show Diagnostic Error Logs"):
                        st.code(update["error"], language="bash")

                if "code" in update:
                    current_code = update["code"]
                    with st.expander("View Code Written So Far"):
                        st.code(current_code, language="python")

                if update.get("final"):
                    final_video_path = update.get("video_path")
                    if not final_video_path:
                        coder_status.update(label="❌ Generation failed", state="error")
                        status.update(label="Failed", state="error", expanded=True)
                        st.stop()

            coder_status.update(label="✅ Manim script generated and verified", state="complete")

        if final_video_path:
            with st.status("🎬 Stitching audio and video...") as stitch_status:
                final_output = os.path.join("output", "final_output.mp4")
                stitch_result = stitch_video_and_audio(final_video_path, audio_path, final_output)

                if stitch_result.get("success"):
                    stitch_status.update(label="✅ Audio and video stitched", state="complete")
                    status.update(label="🎉 Video generation complete!", state="complete", expanded=False)
                    st.success("Successfully generated!")
                    st.video(final_output)
                else:
                    stitch_status.update(label="⚠️ Failed to stitch audio/video", state="error")
                    status.update(label="Video generation complete (no audio)", state="complete", expanded=False)
                    st.warning("Failed to stitch audio and video. You can view the raw animation below:")
                    if stitch_result.get("error"):
                        with st.expander("Show Stitching Error Logs"):
                            st.code(stitch_result["error"], language="text")
                    st.video(final_video_path)
