# paper2manim

Generate beautiful 3Blue1Brown-style educational videos from simple concepts using LLMs, Manim, and self-correcting agents.

## Features

- 🧠 **AI-Powered Planning**: Uses Gemini to create educational storyboards
- 💻 **Automatic Manim Code Generation**: Self-correcting agent loop generates working animations
- 🎙️ **Text-to-Speech Voiceover**: Automatic narration generation
- 🎬 **Complete Video Pipeline**: Combines animation and audio into final video
- 🖥️ **Two Interfaces**: Choose between CLI (fast) or Streamlit (visual)

## Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd paper2manim

# Install dependencies
pip install -r requirements.txt

# Set up your API key
echo "GEMINI_API_KEY=your_key_here" > .env
```

## Usage

### CLI (Recommended for Speed)

```bash
# Generate a video from the command line
python3 cli.py "The Pythagorean Theorem"

# More examples
python3 cli.py "Linear Algebra: Dot Products"
python3 cli.py "Calculus: The Chain Rule"
```

Output will be saved to `output/final_output.mp4`

### Streamlit UI (Visual Interface)

```bash
# Launch the web interface
streamlit run app.py
```

Then open your browser and interact with the visual interface.

## Project Structure

```
paper2manim/
├── cli.py              # Command-line interface (fast, simple)
├── app.py              # Streamlit web interface (visual, interactive)
├── agents/
│   ├── planner.py     # AI storyboard planning agent
│   └── coder.py       # Self-correcting Manim code generator
├── utils/
│   ├── tts_engine.py        # Text-to-speech generation
│   ├── manim_runner.py      # Manim execution and validation
│   └── media_assembler.py   # Video + audio stitching
└── output/            # Generated videos and assets
```

## How It Works

1. **Planning**: Gemini analyzes your concept and creates a storyboard with visual instructions and narration script
2. **Voiceover**: Text-to-speech engine generates audio narration
3. **Animation**: Self-correcting agent generates Manim code, runs it, and fixes errors automatically
4. **Assembly**: FFmpeg combines the animation and audio into the final video

## Requirements

- Python 3.8+
- FFmpeg (for audio/video processing)
- Manim (animation library)
- Gemini API key