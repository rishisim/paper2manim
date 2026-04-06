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
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Iterator, List, Literal

from pydantic import BaseModel, Field

from agents.config import (
    model_profile_summary,
    new_token_counter,
    resolve_fallback_stage_model,
    resolve_stage_model,
)
from utils.llm_provider import run_text_completion

# ── Duration presets: map user's video-length choice to hard constraints ──

DURATION_PRESETS = {
    "Short (1-2 min)":  {"target_seconds": 90,  "min_segments": 2, "max_segments": 3, "per_segment_seconds": 35},
    "Medium (3-5 min)": {"target_seconds": 210, "min_segments": 3, "max_segments": 5, "per_segment_seconds": 50},
    "Long (5-10 min)":  {"target_seconds": 420, "min_segments": 5, "max_segments": 8, "per_segment_seconds": 60},
}
DEFAULT_DURATION_PRESET = DURATION_PRESETS["Medium (3-5 min)"]

_DEFAULT_PALETTE: dict[str, str] = {
    "Background": "#141414",
    "Primary":    "#3B82F6",
    "Secondary":  "#10B981",
    "Accent":     "#FBBF24",
    "Text":       "#FFFFFF",
}

# ── Pydantic models for intermediate stages ──────────────────────────

class ConceptAnalysis(BaseModel):
    core_concept: str = Field(description="The fundamental mathematical/scientific concept")
    domain: str = Field(description="e.g. 'Linear Algebra', 'Calculus', 'Quantum Physics'")
    target_audience: str = Field(description="e.g. 'undergraduate', 'high school', 'general audience'")
    key_insights: List[str] = Field(description="3-5 'aha moments' that make this concept click")
    common_misconceptions: List[str] = Field(description="2-3 common mistakes or misunderstandings to address")
    narrative_arc: str = Field(description="Suggested story arc: e.g. 'intuition → formalism → application'")
    suggested_segment_count: int = Field(ge=2, le=8, description="Recommended number of video segments")


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


def _planner_preference_context(questionnaire_answers: dict | None, duration_preset: dict) -> tuple[str, str]:
    """Return enriched concept context and a prompt suffix derived from user preferences."""
    if not questionnaire_answers:
        return "", ""

    target_audience = questionnaire_answers.get("target_audience", "Undergraduate")
    visual_style = questionnaire_answers.get("visual_style", "Let the AI decide")
    pacing = questionnaire_answers.get("pacing", "Balanced")
    narration_style = questionnaire_answers.get("narration_style", "standard")
    quality_mode = questionnaire_answers.get("quality_mode", "balanced")

    audience_guidance = {
        "High school student": "Prefer intuition-first explanations, define symbols before use, and avoid compressed notation leaps.",
        "Undergraduate": "Balance intuition with formal notation and introduce symbols right before they are used.",
        "Graduate / Professional": "Assume mathematical maturity, but still keep symbol introductions explicit and purposeful.",
        "General audience": "Minimize jargon, prioritize metaphor and visual intuition, and define every symbol in plain language.",
    }.get(target_audience, "Introduce notation carefully and keep the explanation audience-appropriate.")

    style_guidance = {
        "Geometric intuition": "Prioritize diagrams, spatial metaphors, and motion that builds intuition before algebraic detail.",
        "Step-by-step derivation": "Keep the screen sparse and structure each segment around one derivation step at a time.",
        "Real-world applications": "Anchor each segment in motivating examples and reserve equations for the minimum needed formalism.",
        "Let the AI decide": "Choose the visual approach that best supports understanding while keeping scenes uncluttered.",
    }.get(visual_style, "Choose the visual approach that best supports understanding while keeping scenes uncluttered.")

    pacing_guidance = {
        "Fast and dense": ("Move briskly, but still avoid clutter and leave a brief hold after each major beat.", "high"),
        "Balanced": ("Use a clear beat structure with breathing room after important reveals.", "medium"),
        "Slow and exploratory": ("Use fewer simultaneous objects, longer holds, and especially low visual density.", "low"),
    }.get(pacing, ("Use a clear beat structure with breathing room after important reveals.", "medium"))

    narration_guidance = {
        "concise": "Keep narration efficient and low on repetition.",
        "standard": "Use clear, natural narration with a moderate amount of intuition.",
        "intuitive": "Spend more words on intuition, analogy, and why each step matters.",
    }.get(narration_style, "Use clear, natural narration with a moderate amount of intuition.")

    quality_guidance = {
        "fast": "Optimize for reliable, simpler scenes over ambitious density.",
        "balanced": "Aim for polished results with one strong idea on screen at a time.",
        "polished": "Favor the most polished, consistent output with especially strong transitions and end frames.",
    }.get(quality_mode, "Aim for polished results with one strong idea on screen at a time.")

    pref_parts = [
        f"Video length: {questionnaire_answers.get('video_length', 'Medium (3-5 min)')} (HARD CONSTRAINT: ~{duration_preset['target_seconds']}s)",
        f"Target audience: {target_audience}",
        f"Visual style: {visual_style}",
        f"Pacing: {pacing}",
        f"Narration style: {narration_style}",
        f"Quality mode: {quality_mode}",
        f"Maximum visual density: {pacing_guidance[1]}",
    ]
    for q, a in questionnaire_answers.get("custom_preferences", {}).items():
        pref_parts.append(f"{q}: {a}")

    preference_suffix = (
        "\n\nImplementation preferences:\n"
        f"- {audience_guidance}\n"
        f"- {style_guidance}\n"
        f"- {pacing_guidance[0]}\n"
        f"- {narration_guidance}\n"
        f"- {quality_guidance}\n"
        "- Explicitly forbid introducing symbols before defining them.\n"
        "- Explicitly forbid overloading the screen with too many simultaneous independent objects.\n"
        "- Every segment must end on a stable, meaningful frame.\n"
        "- Every segment must either acknowledge carry-over from the previous segment or begin from a clean reset.\n"
    )

    enriched_concept = "\n\nUser preferences:\n" + "\n".join(f"- {p}" for p in pref_parts)
    return enriched_concept, preference_suffix


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


def _call_llm(
    prompt: str,
    *,
    max_tokens: int = 4096,
    token_counter: dict | None = None,
    cache_key_label: str = "planner",
) -> str:
    """Make a single planner LLM call and return the raw text.

    Args:
        max_tokens: Output token ceiling. Stages 1-4 produce small JSON so 4096
            is more than enough. Stage 5 narrative composition should pass 8192.
        token_counter: If provided, input/output token counts from the response
            are accumulated into this dict.
    """
    primary = resolve_stage_model("plan")
    fallback = resolve_fallback_stage_model("plan")
    result = run_text_completion(
        primary=primary,
        fallback=fallback,
        system_sections=[
            "You are an expert JSON generator. Output ONLY valid JSON - no markdown fences, no explanation, no preamble. Your response must start with '{' or '['."
        ],
        user_content=prompt + "\n\nRespond with ONLY the JSON object, nothing else.",
        max_output_tokens=max_tokens,
        token_counter=token_counter,
        cache_key_parts=(cache_key_label, primary.model),
    )
    return result.text


def _call_stage_with_retries(fn, *args, max_retries: int = 3, stage_name: str = "stage"):
    """Call fn(*args) up to max_retries times with exponential backoff.

    Returns (result, last_error_str). result is None if all attempts failed.
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            result = fn(*args)
            if result is not None:
                return result, None
            last_error = "returned None without raising"
        except Exception as e:
            last_error = str(e)
            print(f"{stage_name} attempt {attempt + 1}/{max_retries} failed: {e}", file=sys.stderr)
        if attempt < max_retries - 1:
            time.sleep(min(2 ** attempt, 8))
    return None, last_error


def _friendly_planner_error(err: str | None) -> str:
    """Map low-level planner errors to concise, user-actionable text."""
    if not err:
        return "unknown error"
    low = err.lower()
    if "credit balance" in low or "billing" in low:
        return "LLM billing/credit issue"
    if "authentication" in low or "invalid x-api-key" in low or "api key" in low or "401" in low:
        return "LLM authentication failed (check your API keys, especially ANTHROPIC_API_KEY / OPENAI_API_KEY)"
    if "model" in low and ("not found" in low or "does not exist" in low or "invalid" in low):
        return "configured model is unavailable"
    return err


def _default_prerequisite_tree(concept: str, analysis: ConceptAnalysis | None) -> PrerequisiteTree:
    """Minimal fallback tree when LLM-based discovery fails."""
    seg_count = analysis.suggested_segment_count if analysis else 3
    nodes = []
    if seg_count >= 3:
        nodes.append(ConceptNode(id=1, title=f"Foundations for {concept}", description="Establish the necessary background.", complexity="simple"))
    nodes.append(ConceptNode(id=len(nodes) + 1, title=f"Core ideas of {concept}", description="Develop the central concepts.", complexity="complex"))
    nodes.append(ConceptNode(id=len(nodes) + 1, title=concept, description="The target concept itself.", complexity="complex"))
    return PrerequisiteTree(nodes=nodes)


def _default_enriched_tree(tree: PrerequisiteTree) -> EnrichedTree:
    """Minimal fallback enrichment when LLM-based enrichment fails."""
    return EnrichedTree(nodes=[
        EnrichedNode(
            id=n.id, title=n.title, description=n.description, complexity=n.complexity,
            equations_latex=[], variable_definitions={}, elements=[], visual_metaphor="",
        )
        for n in tree.nodes
    ])


# ── Stage 1: Concept Analysis ────────────────────────────────────────

def analyze_concept(concept: str, client: object | None, duration_preset: dict | None = None, token_counter: dict | None = None) -> ConceptAnalysis:
    preset = duration_preset or DEFAULT_DURATION_PRESET
    min_seg, max_seg = preset["min_segments"], preset["max_segments"]
    target_secs = preset["target_seconds"]

    prompt = f"""You are an expert pedagogical planner and mathematical educator.
The user wants to create an educational video about: "{concept}"

HARD CONSTRAINT: The video must be approximately {target_secs} seconds ({target_secs // 60}-{(target_secs + 59) // 60} minutes) long.
You MUST suggest between {min_seg} and {max_seg} segments. Do NOT exceed {max_seg} segments.

Analyze this concept deeply and output JSON matching this schema:
{{
  "core_concept": "the fundamental concept being taught",
  "domain": "the mathematical/scientific domain",
  "target_audience": "assumed audience level",
  "key_insights": ["insight 1", "insight 2", "..."],
  "common_misconceptions": ["misconception 1", "..."],
  "narrative_arc": "describe the story structure: e.g. 'start with geometric intuition, formalize with algebra, demonstrate with application'",
  "suggested_segment_count": {min_seg}
}}

Think about:
- What makes this concept CLICK? What are the "aha" moments?
- What do students commonly get wrong?
- What narrative flow would be most engaging for a 3Blue1Brown-style video?
- How to fit this into {min_seg}-{max_seg} segments of ~{preset['per_segment_seconds']}s each?
"""
    text = _extract_json_text(_call_llm(prompt, token_counter=token_counter, cache_key_label="planner-stage1"))
    if not text.strip():
        raise ValueError("empty response from model")
    analysis = ConceptAnalysis.model_validate(json.loads(text))
    # Hard clamp segment count to preset range
    analysis.suggested_segment_count = max(min_seg, min(max_seg, analysis.suggested_segment_count))
    return analysis


# ── Stage 2: Prerequisite Discovery ──────────────────────────────────

def build_prerequisite_tree(concept: str, analysis: ConceptAnalysis | None, client: object | None, token_counter: dict | None = None) -> PrerequisiteTree | None:
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
    text = _extract_json_text(_call_llm(prompt, token_counter=token_counter, cache_key_label="planner-stage2"))
    return PrerequisiteTree.model_validate(json.loads(text))


# ── Stage 3: Mathematical Enrichment ─────────────────────────────────

def enrich_concept_tree(tree: PrerequisiteTree, analysis: ConceptAnalysis | None, client: object | None, token_counter: dict | None = None) -> EnrichedTree | None:
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
    text = _extract_json_text(_call_llm(prompt, token_counter=token_counter, cache_key_label="planner-stage3"))
    return EnrichedTree.model_validate(json.loads(text))


# ── Stage 4: Visual Design ───────────────────────────────────────────

def design_visuals(enriched_tree: EnrichedTree, analysis: ConceptAnalysis | None, client: object | None, token_counter: dict | None = None) -> VisualDesign | None:
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
    text = _extract_json_text(_call_llm(prompt, token_counter=token_counter, cache_key_label="planner-stage4"))
    return VisualDesign.model_validate(json.loads(text))


# ── Stage 5: Narrative Composition (per-segment for speed) ────────────

def _compose_single_segment(
    node: EnrichedNode,
    segment_index: int,
    total_segments: int,
    visual_design: VisualDesign | None,
    analysis: ConceptAnalysis | None,
    enriched_tree: EnrichedTree,
    client: object | None,
    max_retries: int = 2,
    per_segment_seconds: int = 50,
    token_counter: dict | None = None,
    planner_preferences: str = "",
) -> dict | None:
    """Compose a single segment's narrative. Returns the segment dict or None."""

    # Build context
    palette = json.dumps(visual_design.color_palette) if visual_design else json.dumps(_DEFAULT_PALETTE)
    theme = visual_design.theme_name if visual_design else "Classic 3b1b"

    seg_design = ""
    if visual_design and segment_index < len(visual_design.segment_designs):
        sd = visual_design.segment_designs[segment_index]
        seg_design = f"""
Layout Blueprint: {sd.layout_blueprint}
Camera Notes: {sd.camera_notes}
Transition In: {sd.transition_in}
Transition Out: {sd.transition_out}"""

    # Provide full sequence context so the model knows where this segment fits
    sequence_summary = " → ".join(f"[{i+1}] {n.title}" for i, n in enumerate(enriched_tree.nodes))

    narrative_context = ""
    if analysis:
        narrative_context = f"""
Narrative Arc: {analysis.narrative_arc}
Key Insights: {json.dumps(analysis.key_insights)}
Misconceptions to Address: {json.dumps(analysis.common_misconceptions)}"""

    # Calculate target word count for audio script (~150 words per minute)
    target_word_count = int(per_segment_seconds * 150 / 60)

    prompt = f"""You are an expert cinematic director, Manim animator, and narrative composer.
Compose ONE segment of a production-ready storyboard for an educational math video.

FULL VIDEO SEQUENCE ({total_segments} segments): {sequence_summary}
YOU ARE COMPOSING SEGMENT {segment_index + 1} of {total_segments}: "{node.title}"

HARD DURATION CONSTRAINT: This segment MUST be exactly ~{per_segment_seconds} seconds long.
- Set duration_hint_seconds to {per_segment_seconds}
- The audio_script MUST be approximately {target_word_count} words (at ~150 words/min speaking pace)
- Do NOT write a longer audio_script — this directly controls video length
{narrative_context}
{planner_preferences}

Segment Source Data:
{json.dumps(node.model_dump(), indent=2)}

Visual Design:
- Theme: {theme}
- Color Palette: {palette}
{seg_design}

Output a SINGLE JSON object for this segment:
{{
  "id": {node.id},
  "title": "{node.title}",
  "learning_goal": "What the viewer should understand by the end of this segment",
  "must_show": ["critical object or beat 1", "critical object or beat 2"],
  "end_state": "Meaningful object or visual summary that remains visible at the end",
  "carry_over_from_previous": "Either describe the carried-over anchor object or say 'clean reset'",
  "visual_density": "low",
  "equations_latex": ["exact LaTeX strings with DOUBLE backslashes"],
  "variable_definitions": {{"symbol": "meaning"}},
  "elements": ["visual objects to create"],
  "element_colors": {{"element_name": "#HEXCODE"}},
  "animations": ["TransformMatchingTex", "Create", "FadeIn", ...],
  "layout_instructions": "Exact spatial arrangement on screen",
  "visual_instructions": "BEAT-BY-BEAT SCREENPLAY — write every beat in this EXACT format:\nBEAT N [Xs–Ys]:\n  CLEAR: self.play(FadeOut(prev_elem1, prev_elem2), run_time=0.4)  ← REQUIRED if any screen zone is being reused\n  OBJECT: var = ManimClass(...).position_method()\n  ANIMATE: self.play(AnimName(var), run_time=X.X)\n  WAIT: self.wait(X.X)\n  AUDIO CUE: 'first few words of narration synced to this beat'\nScreen zones — ONLY ONE element group per zone at a time:\n  HEADER [top]:   title/heading → .to_edge(UP, buff=0.5)\n  MAIN [center]:  diagram/graph/primary equation → .move_to(ORIGIN)\n  FOOTER [bottom]: secondary equation/label → .to_edge(DOWN, buff=0.5)\nExample:\nBEAT 3 [6–9s]:\n  CLEAR: self.play(FadeOut(intro_text, subtitle), run_time=0.4)\n  OBJECT: axes = Axes(x_range=[-3,3], y_range=[-2,2]).move_to(ORIGIN)\n  ANIMATE: self.play(Create(axes), run_time=1.5)\n  WAIT: self.wait(0.5)\n  AUDIO CUE: 'Now let us visualize the frequency domain...'\nEvery beat MUST include OBJECT constructor, run_time, wait duration, audio sync cue, and CLEAR if reusing a zone.",
  "audio_script": "Engaging voiceover narration (3Blue1Brown style)",
  "duration_hint_seconds": 45,
  "complexity": "{node.complexity}"
}}

CRITICAL RULES FOR visual_instructions:
1. Use the BEAT-BY-BEAT format shown above — numbered beats with timestamps, no free-form prose
2. EXACT Manim constructor calls: Text(...), MathTex(r"..."), Circle(...), Axes(...), etc.
3. EXACT animation calls: Write(), Create(), FadeIn(obj, shift=DIR), TransformMatchingTex(), GrowArrow()
4. EXACT run_time= on every self.play() call
5. EXACT self.wait() durations after each beat
6. EXACT screen positions using Manim constants (UP, DOWN, LEFT, RIGHT, ORIGIN, UL, UR)
7. EXACT color hex codes from the palette — never use generic color names unless they are Manim constants
8. CLEAR step is MANDATORY at any beat that reuses the HEADER, MAIN, or FOOTER zone.
   Name the exact objects to FadeOut: `self.play(FadeOut(title, eq1, diagram), run_time=0.4)`
   Never leave old elements on screen when new ones enter the same zone.
9. Spatial relationships: .next_to(), .align_to(), .shift(), .move_to() as appropriate.
   Labels on graphs/arrows MUST use .next_to(target, direction, buff=0.2) — never .move_to(ORIGIN)
10. The final beat MUST keep at least one meaningful object visible on screen until the narration ends.
    Never spend the last several seconds on an empty or fully black frame.
11. Beat timestamps should cover the full narration span with no large dead zone after the final explanatory beat.
12. Set visual_density to low, medium, or high based on how many independent visual ideas appear simultaneously. Respect the user pacing preference.
13. learning_goal must be a single pedagogical objective, not a summary paragraph.
14. must_show should list the non-negotiable visuals or transformations for this segment.
15. carry_over_from_previous must explicitly say whether to preserve an anchor object or reset cleanly.

{"This is the FIRST segment — establish foundational context before diving in." if segment_index == 0 else ""}
{"This is the FINAL segment — build to a satisfying conclusion." if segment_index == total_segments - 1 else ""}

Respond with ONLY the JSON object, nothing else."""

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            text = _extract_json_text(_call_llm(prompt, max_tokens=8192, token_counter=token_counter, cache_key_label="planner-compose"))
            return json.loads(text)
        except Exception as e:
            last_error = e
            print(f"Segment {node.id} attempt {attempt + 1} failed: {e}", file=sys.stderr)

    # Re-raise the last error so the caller can surface it
    if last_error is not None:
        raise last_error
    return None


def compose_narrative(
    enriched_tree: EnrichedTree,
    visual_design: VisualDesign | None,
    analysis: ConceptAnalysis | None,
    client: object | None,
    max_retries: int = 3,
    duration_preset: dict | None = None,
    token_counter: dict | None = None,
    planner_preferences: str = "",
) -> Iterator[dict]:
    """Compose all segments in parallel for speed, then assemble the storyboard."""
    from agents.planner import ProSegmentedStoryboard  # lazy import

    preset = duration_preset or DEFAULT_DURATION_PRESET
    per_segment_seconds = preset["per_segment_seconds"]
    target_seconds = preset["target_seconds"]

    total = len(enriched_tree.nodes)
    yield {"status": f"Composing {total} segments in parallel (~{per_segment_seconds}s each, target {target_seconds}s total)..."}

    # Launch all segment compositions in parallel
    # L6: Protect results/segment_errors with a lock — futures complete on pool threads
    results: dict[int, dict | None] = {}
    segment_errors: dict[int, str] = {}
    results_lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=min(total, 5)) as pool:
        futures = {
            pool.submit(
                _compose_single_segment,
                node, i, total, visual_design, analysis, enriched_tree, client,
                max_retries, per_segment_seconds, token_counter, planner_preferences,
            ): i
            for i, node in enumerate(enriched_tree.nodes)
        }
        for future in as_completed(futures):
            idx = futures[future]
            node = enriched_tree.nodes[idx]
            try:
                seg_result = future.result()
                with results_lock:
                    results[idx] = seg_result
            except Exception as e:
                err_msg = str(e)
                print(f"Segment {idx + 1} ({node.title}) failed: {err_msg}", file=sys.stderr)
                with results_lock:
                    results[idx] = None
                    segment_errors[idx] = err_msg
            yield {"status": f"  → Segment {idx + 1}/{total} done: {node.title}"}

    # Collect in order
    segments = []
    for i in range(total):
        seg = results.get(i)
        if seg is None:
            err_detail = segment_errors.get(i, "unknown error")
            # Surface billing/auth errors clearly
            if "credit balance" in err_detail.lower() or "billing" in err_detail.lower():
                yield {"final": True, "error": "LLM billing error: check your provider account credits."}
            elif "authentication" in err_detail.lower() or "401" in err_detail:
                yield {"final": True, "error": "LLM authentication failed. Check your configured API keys in .env."}
            else:
                yield {"final": True, "error": f"Failed to compose segment {i + 1} ({enriched_tree.nodes[i].title}): {err_detail}"}
            return
        segments.append(seg)

    # Validate total duration
    total_duration = sum(s.get("duration_hint_seconds", per_segment_seconds) for s in segments)
    if abs(total_duration - target_seconds) > target_seconds * 0.3:
        print(f"WARNING: Total planned duration {total_duration}s deviates >30% from target {target_seconds}s", file=sys.stderr)
    yield {"status": f"  → Total planned duration: {total_duration}s (target: {target_seconds}s)"}

    # ── Post-validate audio_script word counts ──────────────────────────────
    # Segments whose audio_script is >40% off the target word count will produce
    # videos significantly shorter or longer than planned. Re-generate once.
    target_words = int(per_segment_seconds * 150 / 60)
    _WORD_TOLERANCE = 0.40
    for i, seg in enumerate(segments):
        actual_words = len(seg.get("audio_script", "").split())
        deviation = abs(actual_words - target_words) / max(target_words, 1)
        if deviation > _WORD_TOLERANCE:
            node = enriched_tree.nodes[i]
            yield {
                "status": (
                    f"  → Segment {i + 1} audio script is {actual_words} words "
                    f"(target ~{target_words}) — regenerating for better timing..."
                )
            }
            try:
                new_seg = _compose_single_segment(
                    node, i, total, visual_design, analysis, enriched_tree,
                    client, max_retries, per_segment_seconds, token_counter, planner_preferences,
                )
                if new_seg:
                    new_words = len(new_seg.get("audio_script", "").split())
                    new_dev = abs(new_words - target_words) / max(target_words, 1)
                    if new_dev < deviation:
                        segments[i] = new_seg
                        yield {"status": f"  → Segment {i + 1} regenerated: {new_words} words (improved)"}
                    else:
                        yield {"status": f"  → Segment {i + 1} regeneration did not improve word count — keeping original"}
            except Exception as e:
                yield {"status": f"  → Segment {i + 1} regeneration failed ({e}) — keeping original"}

    # Assemble final storyboard
    palette = visual_design.color_palette if visual_design else _DEFAULT_PALETTE
    theme = visual_design.theme_name if visual_design else "Classic 3b1b"

    storyboard_dict = {
        "theme_name": theme,
        "color_palette": palette,
        "segments": segments,
    }

    try:
        storyboard = ProSegmentedStoryboard.model_validate(storyboard_dict)
        yield {"final": True, "storyboard": storyboard.model_dump()}
    except Exception as e:
        yield {"final": True, "error": f"Failed to validate assembled storyboard: {e}"}


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
    client = None
    planner_tokens = new_token_counter()

    # Resolve duration preset from questionnaire
    video_length = "Medium (3-5 min)"
    if questionnaire_answers:
        video_length = questionnaire_answers.get("video_length", video_length)
    duration_preset = DURATION_PRESETS.get(video_length, DEFAULT_DURATION_PRESET)

    # Enrich concept with questionnaire preferences if available
    enriched_concept = concept
    planner_preferences = ""
    if questionnaire_answers:
        enriched_pref_context, planner_preferences = _planner_preference_context(questionnaire_answers, duration_preset)
        enriched_concept = f"{concept}{enriched_pref_context}"

    # ── Stage 1: Concept Analysis ──
    yield {"status": f"Stage 1/5: Analyzing concept (target: {duration_preset['target_seconds']}s, {duration_preset['min_segments']}-{duration_preset['max_segments']} segments)..."}
    analysis, analysis_err = _call_stage_with_retries(
        analyze_concept, enriched_concept, client, duration_preset, planner_tokens,
        max_retries=max_retries, stage_name="Stage 1 (concept analysis)",
    )
    if analysis:
        yield {"status": f"  → Domain: {analysis.domain} | Audience: {analysis.target_audience} | Arc: {analysis.narrative_arc[:60]}..."}
    else:
        reason = _friendly_planner_error(analysis_err)
        yield {"status": f"  → Concept analysis failed after {max_retries} attempts: {reason}"}
        yield {"status": "  → Proceeding with defaults..."}

    # ── Stage 2: Prerequisite Discovery ──
    yield {"status": "Stage 2/5: Building reverse knowledge tree (what must be understood first?)..."}
    tree, tree_err = _call_stage_with_retries(
        build_prerequisite_tree, concept, analysis, client, planner_tokens,
        max_retries=max_retries, stage_name="Stage 2 (prerequisite tree)",
    )
    if not tree:
        yield {"status": f"  → Prerequisite tree failed after {max_retries} attempts: {tree_err}"}
        yield {"status": "  → Using minimal fallback tree..."}
        tree = _default_prerequisite_tree(concept, analysis)
    # Hard-clamp tree to duration preset's max segments so a "Short" video
    # never accidentally becomes 6 segments due to the LLM ignoring the constraint.
    max_segs = duration_preset["max_segments"]
    if len(tree.nodes) > max_segs:
        tree = PrerequisiteTree(nodes=tree.nodes[:max_segs])
        yield {"status": f"  → Clamped to {max_segs} segments to satisfy duration constraint"}
    yield {"status": f"  → Built tree with {len(tree.nodes)} nodes: {' → '.join(n.title for n in tree.nodes)}"}

    # ── Stage 3: Mathematical Enrichment ──
    yield {"status": f"Stage 3/5: Enriching {len(tree.nodes)} segments with equations, variables, and visual metaphors..."}
    enriched, enrich_err = _call_stage_with_retries(
        enrich_concept_tree, tree, analysis, client, planner_tokens,
        max_retries=max_retries, stage_name="Stage 3 (enrichment)",
    )
    if not enriched:
        yield {"status": f"  → Enrichment failed after {max_retries} attempts: {enrich_err}"}
        yield {"status": "  → Using minimal fallback enrichment..."}
        enriched = _default_enriched_tree(tree)
    total_equations = sum(len(n.equations_latex) for n in enriched.nodes)
    yield {"status": f"  → Enriched with {total_equations} equations and {len(enriched.nodes)} visual metaphors"}

    # ── Stage 4: Visual Design ──
    yield {"status": "Stage 4/5: Designing visual identity, color palette, and per-segment layouts..."}
    visual_design, _ = _call_stage_with_retries(
        design_visuals, enriched, analysis, client, planner_tokens,
        max_retries=max_retries, stage_name="Stage 4 (visual design)",
    )
    if visual_design:
        yield {"status": f"  → Theme: '{visual_design.theme_name}' with {len(visual_design.color_palette)} colors"}
    else:
        yield {"status": "  → Visual design returned empty, narrative composer will use defaults..."}

    # ── Stage 5: Narrative Composition (parallel) ──
    yield {"status": "Stage 5/5: Composing verbose narrative storyboard (parallel, 2000+ tokens per segment)..."}
    for update in compose_narrative(
        enriched,
        visual_design,
        analysis,
        client,
        max_retries,
        duration_preset=duration_preset,
        token_counter=planner_tokens,
        planner_preferences=planner_preferences,
    ):
        if update.get("final"):
            # Attach planner token usage to the final update
            update["token_usage"] = dict(planner_tokens)
            update["model_profile"] = model_profile_summary()
        yield update
