"""Five-stage prompt enrichment pipeline for Math-to-Manim video generation.

Inspired by the Math-To-Manim project's six-stage approach:
1. Concept Analysis — understand the core concept, audience, and narrative arc
2. Prerequisite Discovery — build a reverse knowledge tree (what must be understood first?)
3. Mathematical Enrichment — add LaTeX equations, definitions, visual metaphors
4. Visual Design — specify color themes, layout blueprints, camera and transitions
5. Narrative Composition — produce verbose 2000+ token specs per segment with exact
   LaTeX strings, animation names, timing, positions, and beat-by-beat visual flow

Output conforms to ProSegmentedStoryboard so the downstream pipeline is unchanged.
"""

import json
import re
from typing import Iterator, Literal, List, Dict
from pydantic import BaseModel, Field, ValidationError
from google import genai

# ── Pydantic models for intermediate stages ──────────────────────────

class ConceptAnalysis(BaseModel):
    core_concept: str = Field(description="The fundamental mathematical/scientific concept")
    domain: str = Field(description="e.g. 'Linear Algebra', 'Calculus', 'Quantum Physics'")
    target_audience: str = Field(description="e.g. 'undergraduate', 'high school', 'general audience'")
    key_insights: List[str] = Field(description="3-5 'aha moments' that make this concept click")
    common_misconceptions: List[str] = Field(description="2-3 common mistakes or misunderstandings to address")
    narrative_arc: str = Field(description="Suggested story arc: e.g. 'intuition → formalism → application'")
    suggested_segment_count: int = Field(ge=3, le=8, description="Recommended number of video segments")


class ConceptNode(BaseModel):
    id: int
    title: str = Field(description="Title of the concept/segment.")
    description: str = Field(description="What this concept is about and why it is a prerequisite.")
    complexity: Literal["simple", "complex"] = Field(default="complex")

class PrerequisiteTree(BaseModel):
    nodes: List[ConceptNode] = Field(min_length=1, description="Ordered list of prerequisites leading up to the target concept.")


class EnrichedNode(BaseModel):
    id: int
    title: str
    description: str
    complexity: Literal["simple", "complex"]
    equations_latex: List[str] = Field(description="Raw LaTeX strings (double backslashes)")
    variable_definitions: Dict[str, str] = Field(description="Maps LaTeX symbols to physical/math meanings")
    elements: List[str] = Field(description="Visual objects like 'graph', 'axes', 'triangle'")
    visual_metaphor: str = Field(description="A metaphor for how this concept is visualized")

class EnrichedTree(BaseModel):
    nodes: List[EnrichedNode]


class SegmentVisualDesign(BaseModel):
    segment_id: int
    layout_blueprint: str = Field(description="Spatial arrangement: where elements go on screen (e.g. 'equation top-center, graph below-right')")
    camera_notes: str = Field(description="Camera suggestions: '2D static', '3D with rotation', 'zoom to detail'")
    transition_in: str = Field(description="How this segment begins (e.g. 'fade from previous', 'clean slate')")
    transition_out: str = Field(description="How this segment ends (e.g. 'fade all out', 'keep equation visible')")

class VisualDesign(BaseModel):
    theme_name: str = Field(description="e.g. 'Classic 3b1b', 'Dark Neon', 'Blueprint'")
    color_palette: Dict[str, str] = Field(description="5-7 named colors as hex codes, e.g. {'Primary': '#3B82F6', 'Accent': '#FBBF24'}")
    typography_notes: str = Field(description="Font sizing guidance: title size, body size, label size")
    segment_designs: List[SegmentVisualDesign] = Field(description="Per-segment visual blueprints")


# ── Helpers ──────────────────────────────────────────────────────────

def _extract_json_text(raw_text: str) -> str:
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        match_arr = re.search(r"\[.*\]", text, re.DOTALL)
        if match_arr:
            return match_arr.group(0)
    return match.group(0) if match else text


def _call_gemini(client: genai.Client, prompt: str, model: str = "gemini-3.1-pro-preview") -> str:
    """Make a single Gemini call and return the raw text."""
    response = client.models.generate_content(model=model, contents=prompt)
    return response.text or ""


# ── Stage 1: Concept Analysis ────────────────────────────────────────

def analyze_concept(concept: str, client: genai.Client) -> ConceptAnalysis | None:
    prompt = f"""You are an expert pedagogical planner and mathematical educator.
The user wants to create an educational video about: "{concept}"

Analyze this concept deeply and output JSON matching this schema:
{{
  "core_concept": "the fundamental concept being taught",
  "domain": "the mathematical/scientific domain",
  "target_audience": "assumed audience level",
  "key_insights": ["insight 1", "insight 2", "..."],
  "common_misconceptions": ["misconception 1", "..."],
  "narrative_arc": "describe the story structure: e.g. 'start with geometric intuition, formalize with algebra, demonstrate with application'",
  "suggested_segment_count": 5
}}

Think about:
- What makes this concept CLICK? What are the "aha" moments?
- What do students commonly get wrong?
- What narrative flow would be most engaging for a 3Blue1Brown-style video?
"""
    try:
        text = _extract_json_text(_call_gemini(client, prompt))
        return ConceptAnalysis.model_validate(json.loads(text))
    except Exception as e:
        print(f"Failed concept analysis: {e}")
        return None


# ── Stage 2: Prerequisite Discovery ──────────────────────────────────

def build_prerequisite_tree(concept: str, analysis: ConceptAnalysis | None, client: genai.Client) -> PrerequisiteTree | None:
    analysis_context = ""
    if analysis:
        analysis_context = f"""
Context from concept analysis:
- Domain: {analysis.domain}
- Target audience: {analysis.target_audience}
- Key insights to build toward: {json.dumps(analysis.key_insights)}
- Narrative arc: {analysis.narrative_arc}
- Suggested segment count: {analysis.suggested_segment_count}
"""

    prompt = f"""You are an expert pedagogical planner. The user wants to learn about: "{concept}"
{analysis_context}
Build a Reverse Knowledge Tree: ask yourself "What must someone understand BEFORE they can understand {concept}?"
Trace this recursively down to foundational topics that the target audience would know.
Then REVERSE the order to create a teaching sequence from foundations up to the target concept.

The final node should BE the target concept itself — not a summary or conclusion.
Aim for {analysis.suggested_segment_count if analysis else 5} segments total.

Output as JSON:
{{
  "nodes": [
    {{
      "id": 1,
      "title": "Foundational concept title",
      "description": "What this covers and why it's needed",
      "complexity": "simple" | "complex"
    }}
  ]
}}
"""
    try:
        text = _extract_json_text(_call_gemini(client, prompt))
        return PrerequisiteTree.model_validate(json.loads(text))
    except Exception as e:
        print(f"Failed to build prerequisite tree: {e}")
        return None


# ── Stage 3: Mathematical Enrichment ─────────────────────────────────

def enrich_concept_tree(tree: PrerequisiteTree, analysis: ConceptAnalysis | None, client: genai.Client) -> EnrichedTree | None:
    misconceptions_note = ""
    if analysis and analysis.common_misconceptions:
        misconceptions_note = f"\nCommon misconceptions to address: {json.dumps(analysis.common_misconceptions)}"

    prompt = f"""You are an expert mathematical enricher and visual designer.
Here is the teaching sequence:
{json.dumps(tree.model_dump(), indent=2)}
{misconceptions_note}

For EACH concept node, enrich it with:
1. Correct LaTeX equations (use DOUBLE backslashes: \\\\frac, \\\\vec, etc.)
2. Variable definitions mapping symbols to meanings
3. Primitive visual elements to draw (vectors, graphs, axes, circles, etc.)
4. A creative visual metaphor that connects math to intuition

Output as JSON:
{{
  "nodes": [
    {{
      "id": 1,
      "title": "...",
      "description": "...",
      "complexity": "...",
      "equations_latex": ["\\\\vec{{v}} \\\\cdot \\\\vec{{w}} = |v||w|\\\\cos\\\\theta"],
      "variable_definitions": {{"\\\\vec{{v}}": "first vector", "\\\\theta": "angle between vectors"}},
      "elements": ["vector arrows", "angle arc", "projection line"],
      "visual_metaphor": "The dot product measures how much one vector 'agrees' with another's direction"
    }}
  ]
}}
"""
    try:
        text = _extract_json_text(_call_gemini(client, prompt))
        return EnrichedTree.model_validate(json.loads(text))
    except Exception as e:
        print(f"Failed to enrich tree: {e}")
        return None


# ── Stage 4: Visual Design ───────────────────────────────────────────

def design_visuals(enriched_tree: EnrichedTree, analysis: ConceptAnalysis | None, client: genai.Client) -> VisualDesign | None:
    prompt = f"""You are an expert cinematic visual designer for mathematical animation videos (3Blue1Brown style).

Here is the enriched teaching sequence:
{json.dumps(enriched_tree.model_dump(), indent=2)}

Design the visual identity and per-segment layout. Output JSON:
{{
  "theme_name": "Classic 3b1b",
  "color_palette": {{
    "Background": "#141414",
    "Primary": "#3B82F6",
    "Secondary": "#10B981",
    "Accent": "#FBBF24",
    "Highlight": "#EF4444",
    "Text": "#FFFFFF",
    "Muted": "#6B7280"
  }},
  "typography_notes": "Titles: 42pt bold, body text: 28pt, labels: 22pt, equations: 36pt",
  "segment_designs": [
    {{
      "segment_id": 1,
      "layout_blueprint": "Title top-center, definition text below, vector diagram center-right",
      "camera_notes": "2D static, no camera movement",
      "transition_in": "Clean slate with fade-in",
      "transition_out": "Keep key equation visible, fade other elements"
    }}
  ]
}}

Design rules:
- Dark background ALWAYS (#141414 or similar)
- Use rich, saturated colors that contrast well on dark backgrounds
- Each element type should have a consistent color throughout (e.g., all vectors in blue, all angles in yellow)
- Design layouts that avoid clutter — use screen space intentionally
- Plan transitions so segments flow naturally into each other
"""
    try:
        text = _extract_json_text(_call_gemini(client, prompt))
        return VisualDesign.model_validate(json.loads(text))
    except Exception as e:
        print(f"Failed to design visuals: {e}")
        return None


# ── Stage 5: Narrative Composition ───────────────────────────────────

def compose_narrative(
    enriched_tree: EnrichedTree,
    visual_design: VisualDesign | None,
    analysis: ConceptAnalysis | None,
    client: genai.Client,
    max_retries: int = 3,
) -> Iterator[dict]:
    """Produce the final ProSegmentedStoryboard with verbose 2000+ token visual_instructions per segment."""

    # Build design context
    design_context = ""
    if visual_design:
        design_context = f"""
Visual Design Specification:
- Theme: {visual_design.theme_name}
- Color Palette: {json.dumps(visual_design.color_palette)}
- Typography: {visual_design.typography_notes}
- Per-segment layouts:
{json.dumps([d.model_dump() for d in visual_design.segment_designs], indent=2)}
"""

    narrative_arc = ""
    if analysis:
        narrative_arc = f"""
Narrative Arc: {analysis.narrative_arc}
Key Insights to Build Toward: {json.dumps(analysis.key_insights)}
Misconceptions to Address: {json.dumps(analysis.common_misconceptions)}
"""

    prompt = f"""You are an expert cinematic director, Manim animator, and narrative composer.
You must produce a VERBOSE, production-ready storyboard. This storyboard will be handed DIRECTLY
to a code generator, so be extremely specific.

Enriched Teaching Sequence:
{json.dumps(enriched_tree.model_dump(), indent=2)}
{design_context}
{narrative_arc}

Output JSON matching this schema EXACTLY:
{{
  "theme_name": "...",
  "color_palette": {{"Element": "#HEXCODE", ...}},
  "segments": [
    {{
      "id": 1,
      "title": "...",
      "equations_latex": ["exact LaTeX strings with DOUBLE backslashes"],
      "variable_definitions": {{"symbol": "meaning"}},
      "elements": ["visual objects to create"],
      "element_colors": {{"element_name": "#HEXCODE"}},
      "animations": ["TransformMatchingTex", "Create", "FadeIn", ...],
      "layout_instructions": "Exact spatial arrangement on screen",
      "visual_instructions": "EXTREMELY VERBOSE (2000+ tokens). Step-by-step chronological instructions...",
      "audio_script": "Engaging voiceover narration",
      "duration_hint_seconds": 45,
      "complexity": "simple" | "complex"
    }}
  ]
}}

CRITICAL RULES FOR visual_instructions (this is the MOST important field):
Each segment's visual_instructions MUST be 2000+ tokens and include:

1. EXACT LaTeX strings to render, formatted for Manim MathTex (e.g., r"\\\\frac{{a}}{{b}}")
2. EXACT Manim animation calls: Write(), Create(), FadeIn(), TransformMatchingTex(), etc.
3. EXACT run_time values for each animation (e.g., "Play Write(title) with run_time=1.5")
4. EXACT self.wait() durations after each animation beat
5. EXACT screen positions using Manim constants (e.g., "Place at UP * 2 + LEFT * 3", "Use .to_edge(UP)")
6. EXACT color references by hex code from the palette
7. A beat-by-beat timeline synced with the audio_script:
   - "Beat 1 (0-3s): Title fades in at top center. self.wait(1.0)"
   - "Beat 2 (3-7s): First equation writes in below title. run_time=2.0, then self.wait(1.5)"
   - etc.
8. Transition instructions: what to FadeOut before new elements appear
9. How elements relate to each other spatially (.next_to(), .align_to(), etc.)

The visual_instructions should read like a shot-by-shot screenplay for an animator.
A coder reading ONLY visual_instructions should be able to write the complete Manim scene
without needing any other context.

ALSO IMPORTANT:
- The very first segment MUST establish foundational prerequisites
- audio_script should be conversational and engaging (3Blue1Brown narration style)
- duration_hint_seconds should account for animation time + breathing room
- Use the color palette consistently across all segments
"""

    last_error = ""
    for attempt in range(max_retries):
        yield {"status": f"Composing verbose narrative storyboard (attempt {attempt + 1})..."}
        try:
            text = _extract_json_text(_call_gemini(client, prompt))
            from agents.planner import ProSegmentedStoryboard  # lazy import
            payload = json.loads(text)
            storyboard = ProSegmentedStoryboard.model_validate(payload)
            yield {"final": True, "storyboard": storyboard.model_dump()}
            return
        except Exception as e:
            last_error = str(e)
            yield {"status": f"Validation failed ({last_error}), retrying..."}

    yield {"final": True, "error": f"Failed to compose narrative: {last_error}"}


# ── Orchestrator: 5-stage pipeline ───────────────────────────────────

def run_math2manim_planner(concept: str, max_retries: int = 3, previous_storyboard: dict | None = None, feedback: str | None = None, questionnaire_answers: dict | None = None) -> Iterator[dict]:
    """Run the full 5-stage enrichment pipeline.

    Stages:
    1. Concept Analysis — understand the concept deeply
    2. Prerequisite Discovery — build reverse knowledge tree
    3. Mathematical Enrichment — add equations, variables, visual elements
    4. Visual Design — specify colors, layouts, transitions
    5. Narrative Composition — produce verbose 2000+ token storyboard
    """
    client = genai.Client()

    # Enrich concept with questionnaire preferences if available
    enriched_concept = concept
    if questionnaire_answers:
        pref_parts = [f"Video length: {questionnaire_answers.get('video_length', 'Medium (3-5 min)')}"]
        pref_parts.append(f"Target audience: {questionnaire_answers.get('target_audience', 'Undergraduate')}")
        for q, a in questionnaire_answers.get("custom_preferences", {}).items():
            pref_parts.append(f"{q}: {a}")
        enriched_concept = f"{concept}\n\nUser preferences:\n" + "\n".join(f"- {p}" for p in pref_parts)

    # ── Stage 1: Concept Analysis ──
    yield {"status": "Stage 1/5: Analyzing concept depth, audience, and narrative arc..."}
    analysis = analyze_concept(enriched_concept, client)
    if analysis:
        yield {"status": f"  → Domain: {analysis.domain} | Audience: {analysis.target_audience} | Arc: {analysis.narrative_arc[:60]}..."}
    else:
        yield {"status": "  → Concept analysis returned empty, proceeding with defaults..."}

    # ── Stage 2: Prerequisite Discovery ──
    yield {"status": "Stage 2/5: Building reverse knowledge tree (what must be understood first?)..."}
    tree = build_prerequisite_tree(concept, analysis, client)
    if not tree:
        yield {"final": True, "error": "Stage 2 failed: could not build prerequisite knowledge tree."}
        return
    yield {"status": f"  → Built tree with {len(tree.nodes)} nodes: {' → '.join(n.title for n in tree.nodes)}"}

    # ── Stage 3: Mathematical Enrichment ──
    yield {"status": f"Stage 3/5: Enriching {len(tree.nodes)} segments with equations, variables, and visual metaphors..."}
    enriched = enrich_concept_tree(tree, analysis, client)
    if not enriched:
        yield {"final": True, "error": "Stage 3 failed: could not enrich the knowledge tree."}
        return
    total_equations = sum(len(n.equations_latex) for n in enriched.nodes)
    yield {"status": f"  → Enriched with {total_equations} equations and {len(enriched.nodes)} visual metaphors"}

    # ── Stage 4: Visual Design ──
    yield {"status": "Stage 4/5: Designing visual identity, color palette, and per-segment layouts..."}
    visual_design = design_visuals(enriched, analysis, client)
    if visual_design:
        yield {"status": f"  → Theme: '{visual_design.theme_name}' with {len(visual_design.color_palette)} colors"}
    else:
        yield {"status": "  → Visual design returned empty, narrative composer will use defaults..."}

    # ── Stage 5: Narrative Composition ──
    yield {"status": "Stage 5/5: Composing verbose narrative storyboard (2000+ tokens per segment)..."}
    for update in compose_narrative(enriched, visual_design, analysis, client, max_retries):
        yield update
