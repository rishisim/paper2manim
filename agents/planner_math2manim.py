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

from pydantic import BaseModel, Field, field_validator

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


def _normalize_complexity(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"simple", "intro", "easy", "low"}:
        return "simple"
    if raw in {"medium", "moderate", "mid", "intermediate"}:
        return "medium"
    if raw in {"complex", "hard", "advanced", "high"}:
        return "complex"
    return "complex"

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
    complexity: Literal["simple", "medium", "complex"] = Field(default="complex")

    @field_validator("complexity", mode="before")
    @classmethod
    def _coerce_complexity(cls, value: object) -> str:
        return _normalize_complexity(value)

class PrerequisiteTree(BaseModel):
    nodes: List[ConceptNode] = Field(min_length=1, description="Ordered list of prerequisites leading up to the target concept.")


class EnrichedNode(BaseModel):
    id: int
    title: str
    description: str
    complexity: Literal["simple", "medium", "complex"]
    equations_latex: List[str] = Field(description="Raw LaTeX strings (double backslashes)")
    variable_definitions: Dict[str, str] = Field(description="Maps LaTeX symbols to physical/math meanings")
    elements: List[str] = Field(description="Visual objects like 'graph', 'axes', 'triangle'")
    visual_metaphor: str = Field(description="A metaphor for how this concept is visualized")

    @field_validator("complexity", mode="before")
    @classmethod
    def _coerce_complexity(cls, value: object) -> str:
        return _normalize_complexity(value)

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


class BlueprintSegment(BaseModel):
    id: int
    title: str
    description: str
    complexity: Literal["simple", "medium", "complex"] = "complex"
    equations_latex: List[str] = Field(default_factory=list)
    variable_definitions: Dict[str, str] = Field(default_factory=dict)
    elements: List[str] = Field(default_factory=list)
    visual_metaphor: str = ""
    layout_blueprint: str = ""
    camera_notes: str = "2D static"
    transition_in: str = "Clean slate with fade-in"
    transition_out: str = "Keep a meaningful anchor visible at the end"

    @field_validator("complexity", mode="before")
    @classmethod
    def _coerce_complexity(cls, value: object) -> str:
        return _normalize_complexity(value)


class PlanningBlueprint(BaseModel):
    analysis: ConceptAnalysis
    theme_name: str = "Classic 3b1b"
    color_palette: Dict[str, str] = Field(default_factory=lambda: dict(_DEFAULT_PALETTE))
    typography_notes: str = "Titles: 42pt bold, body text: 28pt, labels: 22pt, equations: 36pt"
    segments: List[BlueprintSegment] = Field(min_length=1)


class SegmentBeatDraft(BaseModel):
    start_s: float = Field(ge=0, description="Beat start timestamp in seconds")
    end_s: float = Field(gt=0, description="Beat end timestamp in seconds")
    goal: str = Field(min_length=1, description="What the viewer should understand from this beat")
    objects: List[str] = Field(default_factory=list, description="Objects introduced or emphasized in this beat")
    animation_intent: str = Field(min_length=1, description="High-level animation/staging intent")
    cleanup: List[str] = Field(default_factory=list, description="Objects or zones that should be cleared before this beat")
    audio_cue: str = Field(min_length=1, description="Short audio phrase to align with this beat")


class SegmentNarrativeDraft(BaseModel):
    id: int = Field(ge=1)
    title: str
    learning_goal: str
    must_show: List[str]
    end_state: str
    carry_over_from_previous: str
    visual_density: Literal["low", "medium", "high"] = "medium"
    scene_strategy: Literal["clean_reset", "carry_anchor", "single_focus_derivation", "diagram_then_equation"] = "clean_reset"
    render_risk: Literal["low", "medium", "high"] = "medium"
    expensive_features_allowed: bool = False
    final_anchor_required: str
    equations_latex: List[str]
    variable_definitions: Dict[str, str]
    elements: List[str]
    element_colors: Dict[str, str]
    animations: List[str]
    layout_instructions: str
    beats: List[SegmentBeatDraft] = Field(min_length=1)
    audio_script: str
    duration_hint_seconds: int
    complexity: Literal["simple", "medium", "complex"] = "complex"

    @field_validator("complexity", mode="before")
    @classmethod
    def _coerce_complexity(cls, value: object) -> str:
        return _normalize_complexity(value)


class SegmentBatchNarrativeDraft(BaseModel):
    segments: List[SegmentNarrativeDraft] = Field(min_length=1, max_length=2)


_PLANNER_JSON_SYSTEM = (
    "You are an expert JSON generator. Output ONLY valid JSON - no markdown fences, "
    "no explanation, no preamble. Your response must start with '{' or '['."
)

_SEGMENT_COMPOSITION_SYSTEM = """You are composing one segment of a production-ready storyboard for an educational math animation.

Output compact JSON for a single segment. Use a `beats` array instead of a giant free-form screenplay.

Rules:
- Keep the segment duration aligned to the requested target duration and speaking pace.
- Use exact `equations_latex` strings and preserve exact hex colors in `element_colors`.
- Keep one primary idea on screen at a time unless grouped intentionally.
- Prefer low-risk scene strategies: `clean_reset`, `carry_anchor`, `single_focus_derivation`, or `diagram_then_equation`.
- Set `render_risk` to `low` unless the concept truly requires dense motion, 3D, or fragile choreography.
- Set `expensive_features_allowed` to true only when 3D, updaters, or unusually dense transforms are clearly justified.
- The final beat must hold a meaningful anchor object through the end of the narration.
- `cleanup` should list exact objects or zones to clear before the beat begins; use an empty list when no cleanup is needed.
- `objects` should name the visible or newly introduced objects for that beat.
- `animation_intent` should describe the motion and staging clearly, but not raw Manim code.
- `audio_cue` should quote or paraphrase the phrase that syncs to the beat.
- Keep beats chronological and cover the narration span without a dead zone at the end.
"""


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
        "balanced": "Aim for polished results with one strong idea on screen at a time, and prefer lower-risk layouts that should pass without repair.",
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
        "- Prefer scene strategies that naturally avoid verification failures: clean resets, a preserved anchor, or one focused derivation at a time.\n"
        "- Prefer cheap, reliable primitives unless the concept clearly requires 3D, dense graphing, or updater-driven motion.\n"
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


def _format_beat_seconds(value: float) -> str:
    rounded = round(float(value), 1)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.1f}"


def _render_beats_to_visual_instructions(draft: SegmentNarrativeDraft) -> str:
    beat_lines: list[str] = []
    for index, beat in enumerate(draft.beats, start=1):
        cleanup = ", ".join(beat.cleanup) if beat.cleanup else "none"
        objects = ", ".join(beat.objects) if beat.objects else "none"
        beat_lines.extend([
            f"BEAT {index} [{_format_beat_seconds(beat.start_s)}s–{_format_beat_seconds(beat.end_s)}s]:",
            f"  GOAL: {beat.goal}",
            f"  OBJECTS: {objects}",
            f"  CLEANUP: {cleanup}",
            f"  ANIMATION INTENT: {beat.animation_intent}",
            f"  AUDIO CUE: {beat.audio_cue}",
        ])
    return "\n".join(beat_lines)


def _draft_to_segment_dict(draft: SegmentNarrativeDraft) -> dict:
    payload = draft.model_dump(exclude={"beats"})
    payload["visual_instructions"] = _render_beats_to_visual_instructions(draft)
    return payload


_BEAT_RANGE_RE = re.compile(r"BEAT\s+\d+\s+\[(?P<start>\d+(?:\.\d+)?)s[–-](?P<end>\d+(?:\.\d+)?)s\]:")


def _segment_batches(total_segments: int) -> list[list[int]]:
    return [list(range(start, min(start + 2, total_segments))) for start in range(0, total_segments, 2)]


def _beat_coverage_score(segment: dict, expected_seconds: int) -> float:
    visual_instructions = segment.get("visual_instructions", "")
    matches = list(_BEAT_RANGE_RE.finditer(visual_instructions))
    if not matches:
        return 1.0

    previous_end = 0.0
    max_end = 0.0
    for match in matches:
        start = float(match.group("start"))
        end = float(match.group("end"))
        if end <= start or start < previous_end:
            return 1.0
        previous_end = end
        max_end = max(max_end, end)

    if expected_seconds <= 0:
        return 0.0
    coverage_ratio = max_end / float(expected_seconds)
    if coverage_ratio >= 0.7:
        return 0.0
    return 0.7 - coverage_ratio


def _catastrophic_retry_score(segment: dict, target_words: int, expected_seconds: int) -> float:
    actual_words = len(segment.get("audio_script", "").split())
    low_words = target_words * 0.6
    high_words = target_words * 1.6
    word_score = 0.0
    if actual_words < low_words:
        word_score = (low_words - actual_words) / max(target_words, 1)
    elif actual_words > high_words:
        word_score = (actual_words - high_words) / max(target_words, 1)

    beat_score = _beat_coverage_score(segment, expected_seconds)
    return max(word_score, beat_score)


def _call_llm(
    prompt: str,
    *,
    max_tokens: int = 4096,
    token_counter: dict | None = None,
    cache_key_label: str = "planner",
    system_sections: list[str] | None = None,
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
        system_sections=system_sections or [_PLANNER_JSON_SYSTEM],
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
    if "literal_error" in low or ("validation error" in low and "pydantic" in low):
        return "planner JSON schema mismatch (received unexpected enum values)"
    if "validation errors for" in low:
        return "planner JSON schema mismatch (validation failed)"
    # Keep the surface message concise: first non-empty line, no docs URLs.
    first_line = next((line.strip() for line in err.splitlines() if line.strip()), "unknown error")
    first_line = re.sub(r"https?://\S+", "", first_line).strip()
    if len(first_line) > 140:
        first_line = f"{first_line[:139]}…"
    return first_line or "unknown error"


def _blueprint_to_enriched_tree(blueprint: PlanningBlueprint) -> EnrichedTree:
    return EnrichedTree(nodes=[
        EnrichedNode(
            id=segment.id,
            title=segment.title,
            description=segment.description,
            complexity=segment.complexity,
            equations_latex=segment.equations_latex,
            variable_definitions=segment.variable_definitions,
            elements=segment.elements,
            visual_metaphor=segment.visual_metaphor,
        )
        for segment in blueprint.segments
    ])


def _blueprint_to_visual_design(blueprint: PlanningBlueprint) -> VisualDesign:
    return VisualDesign(
        theme_name=blueprint.theme_name,
        color_palette=blueprint.color_palette,
        typography_notes=blueprint.typography_notes,
        segment_designs=[
            SegmentVisualDesign(
                segment_id=segment.id,
                layout_blueprint=segment.layout_blueprint,
                camera_notes=segment.camera_notes,
                transition_in=segment.transition_in,
                transition_out=segment.transition_out,
            )
            for segment in blueprint.segments
        ],
    )


def build_planning_blueprint(
    concept: str,
    client: object | None,
    duration_preset: dict | None = None,
    token_counter: dict | None = None,
) -> PlanningBlueprint:
    preset = duration_preset or DEFAULT_DURATION_PRESET
    min_seg, max_seg = preset["min_segments"], preset["max_segments"]
    target_secs = preset["target_seconds"]

    prompt = f"""You are an expert pedagogical planner and visual designer for mathematical animation videos.
The user wants a video about: "{concept}"

Create ONE compact planning blueprint that combines:
- concept analysis
- ordered segment sequence
- mathematical enrichment
- visual identity and per-segment layout notes

Hard constraints:
- Total duration target: about {target_secs} seconds
- Segment count: between {min_seg} and {max_seg}
- Prefer low-risk, legible scenes that still feel polished
- The final segment must be the target concept itself, not just a recap

Output JSON with this shape:
{{
  "analysis": {{
    "core_concept": "fundamental idea",
    "domain": "domain name",
    "target_audience": "audience level",
    "key_insights": ["insight 1", "insight 2"],
    "common_misconceptions": ["misconception 1"],
    "narrative_arc": "intuition -> formalism -> payoff",
    "suggested_segment_count": {min_seg}
  }},
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
  "typography_notes": "short typography guidance",
  "segments": [
    {{
      "id": 1,
      "title": "segment title",
      "description": "what this segment teaches and why it matters",
      "complexity": "simple",
      "equations_latex": ["\\\\theta = ..."],
      "variable_definitions": {{"\\\\theta": "angle"}},
      "elements": ["axes", "unit circle"],
      "visual_metaphor": "short metaphor",
      "layout_blueprint": "where everything goes on screen",
      "camera_notes": "2D static or a safe camera note",
      "transition_in": "how this segment begins relative to the previous one",
      "transition_out": "how this segment should leave a meaningful anchor"
    }}
  ]
}}

Rules:
- Use exact LaTeX with double backslashes.
- Keep segment order pedagogically progressive.
- Keep per-segment descriptions concrete enough for a downstream composer.
- Prefer simple/medium-complexity segment designs unless the concept clearly demands more.
- Transition notes should encode carry-over intent when useful and clean resets when not.
"""
    text = _extract_json_text(_call_llm(prompt, token_counter=token_counter, cache_key_label="planner-blueprint"))
    blueprint = PlanningBlueprint.model_validate(json.loads(text))

    if len(blueprint.segments) > max_seg:
        blueprint = blueprint.model_copy(update={"segments": blueprint.segments[:max_seg]})
    if len(blueprint.segments) < min_seg:
        raise ValueError(f"planner returned only {len(blueprint.segments)} segments; need at least {min_seg}")

    normalized_segments: list[BlueprintSegment] = []
    for i, segment in enumerate(blueprint.segments, start=1):
        normalized_segments.append(segment.model_copy(update={"id": i}))
    analysis = blueprint.analysis.model_copy(update={"suggested_segment_count": len(normalized_segments)})
    return blueprint.model_copy(update={"analysis": analysis, "segments": normalized_segments})


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

    palette = json.dumps(visual_design.color_palette if visual_design else _DEFAULT_PALETTE, separators=(",", ":"))
    theme = visual_design.theme_name if visual_design else "Classic 3b1b"
    previous_title = enriched_tree.nodes[segment_index - 1].title if segment_index > 0 else "None"
    next_title = enriched_tree.nodes[segment_index + 1].title if segment_index + 1 < total_segments else "None"

    seg_design = "No per-segment visual design override."
    if visual_design and segment_index < len(visual_design.segment_designs):
        sd = visual_design.segment_designs[segment_index]
        seg_design = (
            f"Layout Blueprint: {sd.layout_blueprint}\n"
            f"Camera Notes: {sd.camera_notes}\n"
            f"Transition In: {sd.transition_in}\n"
            f"Transition Out: {sd.transition_out}"
        )

    narrative_context = ""
    if analysis:
        narrative_context = (
            f"Narrative Arc: {analysis.narrative_arc}\n"
            f"Key Insights: {json.dumps(analysis.key_insights, separators=(',', ':'))}\n"
            f"Misconceptions to Address: {json.dumps(analysis.common_misconceptions, separators=(',', ':'))}\n"
        )

    target_word_count = int(per_segment_seconds * 150 / 60)
    segment_source = json.dumps(node.model_dump(), separators=(",", ":"))

    prompt = f"""Compose a compact storyboard draft for one segment.

Segment identity:
- Segment {segment_index + 1} of {total_segments}
- Title: {node.title}
- Previous segment: {previous_title}
- Next segment: {next_title}

Timing:
- duration_hint_seconds must be approximately {per_segment_seconds}
- audio_script target length: about {target_word_count} words
- do not overshoot the requested narration length

Creative context:
{narrative_context}{planner_preferences}

Segment source data:
{segment_source}

Visual design:
- Theme: {theme}
- Palette: {palette}
{seg_design}

Output a SINGLE JSON object with this shape:
{{
  "id": {node.id},
  "title": "{node.title}",
  "learning_goal": "single pedagogical objective",
  "must_show": ["critical object or transformation"],
  "end_state": "meaningful closing visual",
  "carry_over_from_previous": "clean reset or carried anchor",
  "visual_density": "low | medium | high",
  "scene_strategy": "clean_reset | carry_anchor | single_focus_derivation | diagram_then_equation",
  "render_risk": "low | medium | high",
  "expensive_features_allowed": false,
  "final_anchor_required": "object that must remain visible at the end",
  "equations_latex": ["exact LaTeX strings"],
  "variable_definitions": {{"symbol": "meaning"}},
  "elements": ["objects that appear in the segment"],
  "element_colors": {{"element": "#HEXCODE"}},
  "animations": ["TransformMatchingTex", "Create", "FadeIn"],
  "layout_instructions": "exact spatial arrangement",
  "beats": [
    {{
      "start_s": 0,
      "end_s": 5,
      "goal": "what this beat teaches",
      "objects": ["object 1", "object 2"],
      "animation_intent": "how the beat should move or reveal information",
      "cleanup": ["object or zone to clear before the beat"],
      "audio_cue": "first words synced to the beat"
    }}
  ],
  "audio_script": "engaging narration",
  "duration_hint_seconds": {per_segment_seconds},
  "complexity": "{node.complexity}"
}}

Do not include `visual_instructions`; it will be rendered from `beats` after this response.
{"This is the FIRST segment — establish foundational context before diving in." if segment_index == 0 else ""}
{"This is the FINAL segment — build to a satisfying conclusion." if segment_index == total_segments - 1 else ""}"""

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            text = _extract_json_text(
                _call_llm(
                    prompt,
                    max_tokens=4096,
                    token_counter=token_counter,
                    cache_key_label="planner-compose-v2",
                    system_sections=[_PLANNER_JSON_SYSTEM, _SEGMENT_COMPOSITION_SYSTEM],
                )
            )
            draft = SegmentNarrativeDraft.model_validate(json.loads(text))
            return _draft_to_segment_dict(draft)
        except Exception as e:
            last_error = e
            print(f"Segment {node.id} attempt {attempt + 1} failed: {e}", file=sys.stderr)

    # Re-raise the last error so the caller can surface it
    if last_error is not None:
        raise last_error
    return None


def _compose_segment_batch(
    indices: list[int],
    enriched_tree: EnrichedTree,
    visual_design: VisualDesign | None,
    analysis: ConceptAnalysis | None,
    client: object | None,
    max_retries: int = 2,
    per_segment_seconds: int = 50,
    token_counter: dict | None = None,
    planner_preferences: str = "",
) -> dict[int, dict]:
    """Compose one or two adjacent segments in a single LLM call.

    Falls back to per-segment composition if the batch response does not validate.
    """
    total_segments = len(enriched_tree.nodes)
    nodes = [enriched_tree.nodes[i] for i in indices]
    batch_size = len(nodes)
    theme = visual_design.theme_name if visual_design else "Classic 3b1b"
    palette = json.dumps(visual_design.color_palette if visual_design else _DEFAULT_PALETTE, separators=(",", ":"))
    outer_previous = enriched_tree.nodes[indices[0] - 1].title if indices[0] > 0 else "None"
    outer_next = enriched_tree.nodes[indices[-1] + 1].title if indices[-1] + 1 < total_segments else "None"

    segment_specs: list[dict] = []
    for local_index, node in zip(indices, nodes):
        seg_design = None
        if visual_design and local_index < len(visual_design.segment_designs):
            sd = visual_design.segment_designs[local_index]
            seg_design = {
                "layout_blueprint": sd.layout_blueprint,
                "camera_notes": sd.camera_notes,
                "transition_in": sd.transition_in,
                "transition_out": sd.transition_out,
            }
        segment_specs.append({
            "segment_number": local_index + 1,
            "total_segments": total_segments,
            "previous_segment": enriched_tree.nodes[local_index - 1].title if local_index > 0 else "None",
            "next_segment": enriched_tree.nodes[local_index + 1].title if local_index + 1 < total_segments else "None",
            "source": node.model_dump(),
            "visual_design": seg_design,
        })

    narrative_context = ""
    if analysis:
        narrative_context = (
            f"Narrative Arc: {analysis.narrative_arc}\n"
            f"Key Insights: {json.dumps(analysis.key_insights, separators=(',', ':'))}\n"
            f"Misconceptions to Address: {json.dumps(analysis.common_misconceptions, separators=(',', ':'))}\n"
        )

    target_word_count = int(per_segment_seconds * 150 / 60)
    prompt = f"""Compose a compact storyboard batch for {batch_size} adjacent segment(s).

Batch continuity:
- Outer previous segment: {outer_previous}
- Outer next segment: {outer_next}
- Theme: {theme}
- Palette: {palette}
- Target per-segment duration: about {per_segment_seconds} seconds
- Target per-segment narration length: about {target_word_count} words

Creative context:
{narrative_context}{planner_preferences}

Segment batch source data:
{json.dumps(segment_specs, separators=(",", ":"))}

Output ONE JSON object with this shape:
{{
  "segments": [
    {{
      "id": 1,
      "title": "segment title",
      "learning_goal": "single pedagogical objective",
      "must_show": ["critical object or transformation"],
      "end_state": "meaningful closing visual",
      "carry_over_from_previous": "clean reset or carried anchor",
      "visual_density": "low | medium | high",
      "scene_strategy": "clean_reset | carry_anchor | single_focus_derivation | diagram_then_equation",
      "render_risk": "low | medium | high",
      "expensive_features_allowed": false,
      "final_anchor_required": "object that must remain visible at the end",
      "equations_latex": ["exact LaTeX strings"],
      "variable_definitions": {{"symbol": "meaning"}},
      "elements": ["objects that appear in the segment"],
      "element_colors": {{"element": "#HEXCODE"}},
      "animations": ["TransformMatchingTex", "Create", "FadeIn"],
      "layout_instructions": "exact spatial arrangement",
      "beats": [
        {{
          "start_s": 0,
          "end_s": 5,
          "goal": "what this beat teaches",
          "objects": ["object 1", "object 2"],
          "animation_intent": "how the beat should move or reveal information",
          "cleanup": ["object or zone to clear before the beat"],
          "audio_cue": "first words synced to the beat"
        }}
      ],
      "audio_script": "engaging narration",
      "duration_hint_seconds": {per_segment_seconds},
      "complexity": "simple | complex"
    }}
  ]
}}

Rules:
- Return exactly {batch_size} segment object(s), one for each source segment, preserving ids and order.
- Do not include `visual_instructions`; it will be rendered from `beats` after this response.
- Keep segment-local continuity explicit: each segment must either preserve a meaningful carry-over or begin from a clean reset.
- Keep beats chronological and cover the narration span without a dead zone at the end.
"""

    last_error: Exception | None = None
    batch_attempts = min(max_retries, 2)
    for attempt in range(batch_attempts):
        try:
            text = _extract_json_text(
                _call_llm(
                    prompt,
                    max_tokens=8192,
                    token_counter=token_counter,
                    cache_key_label="planner-compose-batch-v1",
                    system_sections=[_PLANNER_JSON_SYSTEM, _SEGMENT_COMPOSITION_SYSTEM],
                )
            )
            batch = SegmentBatchNarrativeDraft.model_validate(json.loads(text))
            if len(batch.segments) != batch_size:
                raise ValueError(f"expected {batch_size} segments, got {len(batch.segments)}")

            by_id = {draft.id: draft for draft in batch.segments}
            expected_ids = [node.id for node in nodes]
            if set(by_id) != set(expected_ids):
                raise ValueError(f"batch ids {sorted(by_id)} did not match expected ids {expected_ids}")

            return {
                idx: _draft_to_segment_dict(by_id[node.id])
                for idx, node in zip(indices, nodes)
            }
        except Exception as exc:
            last_error = exc
            print(
                f"Batch {','.join(str(enriched_tree.nodes[i].id) for i in indices)} attempt {attempt + 1} failed: {exc}",
                file=sys.stderr,
            )

    fallback_results: dict[int, dict] = {}
    for idx in indices:
        node = enriched_tree.nodes[idx]
        fallback_results[idx] = _compose_single_segment(
            node,
            idx,
            total_segments,
            visual_design,
            analysis,
            enriched_tree,
            client,
            max_retries=max_retries,
            per_segment_seconds=per_segment_seconds,
            token_counter=token_counter,
            planner_preferences=planner_preferences,
        )
    if not fallback_results and last_error is not None:
        raise last_error
    return fallback_results


def compose_narrative(
    enriched_tree: EnrichedTree,
    visual_design: VisualDesign | None,
    analysis: ConceptAnalysis | None,
    client: object | None,
    max_retries: int = 3,
    duration_preset: dict | None = None,
    token_counter: dict | None = None,
    planner_preferences: str = "",
    stream_segments: bool = False,
) -> Iterator[dict]:
    """Compose all segments in paired batches, then assemble the storyboard."""
    from agents.planner import ProSegmentedStoryboard  # lazy import

    preset = duration_preset or DEFAULT_DURATION_PRESET
    per_segment_seconds = preset["per_segment_seconds"]
    target_seconds = preset["target_seconds"]

    total = len(enriched_tree.nodes)
    batches = _segment_batches(total)
    yield {
        "status": (
            f"Composing {total} segments in {len(batches)} adjacent batch(es) "
            f"(~{per_segment_seconds}s each, target {target_seconds}s total)..."
        )
    }

    results: dict[int, dict | None] = {}
    segment_errors: dict[int, str] = {}
    results_lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=min(len(batches), 5)) as pool:
        futures = {
            pool.submit(
                _compose_segment_batch,
                batch,
                enriched_tree,
                visual_design,
                analysis,
                client,
                max_retries,
                per_segment_seconds,
                token_counter,
                planner_preferences,
            ): batch
            for batch in batches
        }
        for future in as_completed(futures):
            batch = futures[future]
            try:
                seg_results = future.result()
                with results_lock:
                    results.update(seg_results)
            except Exception as e:
                err_msg = str(e)
                print(
                    f"Batch {', '.join(str(i + 1) for i in batch)} failed: {err_msg}",
                    file=sys.stderr,
                )
                with results_lock:
                    for idx in batch:
                        results[idx] = None
                        segment_errors[idx] = err_msg
            for idx in batch:
                node = enriched_tree.nodes[idx]
                update = {"status": f"  → Segment {idx + 1}/{total} done: {node.title}"}
                if stream_segments and results.get(idx) is not None:
                    update["segment_storyboard"] = results[idx]
                    update["segment_id"] = results[idx]["id"]
                    update["num_segments"] = total
                    update["theme_name"] = visual_design.theme_name if visual_design else "Classic 3b1b"
                    update["color_palette"] = visual_design.color_palette if visual_design else _DEFAULT_PALETTE
                yield update

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

    # ── Post-validate catastrophic narration / beat failures ────────────────
    target_words = int(per_segment_seconds * 150 / 60)
    outliers: list[tuple[int, int, float]] = []
    for i, seg in enumerate(segments):
        actual_words = len(seg.get("audio_script", "").split())
        severity = _catastrophic_retry_score(
            seg,
            target_words,
            int(seg.get("duration_hint_seconds", per_segment_seconds) or per_segment_seconds),
        )
        if severity > 0:
            outliers.append((i, actual_words, severity))

    outliers.sort(key=lambda item: item[2], reverse=True)
    outliers = outliers[:2]

    if outliers:
        yield {
            "status": (
                f"  → Regenerating {len(outliers)} catastrophic segment(s) "
                f"(word-count / beat-coverage failures only)..."
            )
        }
        regen_results: dict[int, tuple[dict | None, int | None, float | None, str | None]] = {}
        with ThreadPoolExecutor(max_workers=min(len(outliers), 5)) as pool:
            futures = {
                pool.submit(
                    _compose_single_segment,
                    enriched_tree.nodes[i],
                    i,
                    total,
                    visual_design,
                    analysis,
                    enriched_tree,
                    client,
                    max_retries,
                    per_segment_seconds,
                    token_counter,
                    planner_preferences,
                ): (i, actual_words, deviation)
                for i, actual_words, deviation in outliers
            }
            for future in as_completed(futures):
                i, actual_words, severity = futures[future]
                try:
                    new_seg = future.result()
                    if new_seg:
                        new_words = len(new_seg.get("audio_script", "").split())
                        new_score = _catastrophic_retry_score(
                            new_seg,
                            target_words,
                            int(new_seg.get("duration_hint_seconds", per_segment_seconds) or per_segment_seconds),
                        )
                        regen_results[i] = (new_seg, new_words, new_score, None)
                    else:
                        regen_results[i] = (None, None, None, "empty result")
                except Exception as e:
                    regen_results[i] = (None, None, None, str(e))
                yield {
                    "status": (
                        f"  → Segment {i + 1} retry finished "
                        f"(was {actual_words} words, catastrophic score {severity:.2f})"
                    )
                }

        for i, actual_words, severity in outliers:
            new_seg, new_words, new_score, err = regen_results.get(i, (None, None, None, "missing retry result"))
            if err:
                yield {"status": f"  → Segment {i + 1} regeneration failed ({err}) — keeping original"}
                continue
            assert new_words is not None and new_score is not None
            if new_seg and new_score < severity:
                segments[i] = new_seg
                yield {"status": f"  → Segment {i + 1} regenerated: {new_words} words / score {new_score:.2f} (improved)"}
            else:
                yield {"status": f"  → Segment {i + 1} regeneration did not improve the catastrophic score — keeping original"}

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
    """Run the planner, preferring a compact blueprint + streaming composition path."""
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

    yield {"status": f"Stage 1/2: Building planning blueprint (target: {duration_preset['target_seconds']}s, {duration_preset['min_segments']}-{duration_preset['max_segments']} segments)..."}
    blueprint, blueprint_err = _call_stage_with_retries(
        build_planning_blueprint,
        enriched_concept,
        client,
        duration_preset,
        planner_tokens,
        max_retries=max_retries,
        stage_name="Stage 1 (planning blueprint)",
    )

    analysis: ConceptAnalysis | None
    enriched: EnrichedTree
    visual_design: VisualDesign | None

    if blueprint:
        analysis = blueprint.analysis
        enriched = _blueprint_to_enriched_tree(blueprint)
        visual_design = _blueprint_to_visual_design(blueprint)
        total_equations = sum(len(segment.equations_latex) for segment in blueprint.segments)
        yield {
            "status": (
                f"  → Blueprint ready: {len(blueprint.segments)} segments | "
                f"Theme '{blueprint.theme_name}' | {total_equations} equations"
            )
        }
    else:
        reason = _friendly_planner_error(blueprint_err)
        yield {"status": f"  → Blueprint planning failed after {max_retries} attempts: {reason}"}
        yield {"status": "  → Falling back to multi-stage planner..."}

        analysis, analysis_err = _call_stage_with_retries(
            analyze_concept, enriched_concept, client, duration_preset, planner_tokens,
            max_retries=max_retries, stage_name="Stage 1 fallback (concept analysis)",
        )
        if analysis:
            yield {"status": f"  → Domain: {analysis.domain} | Audience: {analysis.target_audience} | Arc: {analysis.narrative_arc[:60]}..."}
        else:
            reason = _friendly_planner_error(analysis_err)
            yield {"status": f"  → Concept analysis failed after {max_retries} attempts: {reason}"}
            yield {"status": "  → Proceeding with defaults..."}

        tree, tree_err = _call_stage_with_retries(
            build_prerequisite_tree, concept, analysis, client, planner_tokens,
            max_retries=max_retries, stage_name="Stage 2 fallback (prerequisite tree)",
        )
        if not tree:
            yield {"status": f"  → Prerequisite tree failed after {max_retries} attempts: {tree_err}"}
            yield {"status": "  → Using minimal fallback tree..."}
            tree = _default_prerequisite_tree(concept, analysis)
        max_segs = duration_preset["max_segments"]
        if len(tree.nodes) > max_segs:
            tree = PrerequisiteTree(nodes=tree.nodes[:max_segs])
            yield {"status": f"  → Clamped to {max_segs} segments to satisfy duration constraint"}

        enriched, enrich_err = _call_stage_with_retries(
            enrich_concept_tree, tree, analysis, client, planner_tokens,
            max_retries=max_retries, stage_name="Stage 3 fallback (enrichment)",
        )
        if not enriched:
            yield {"status": f"  → Enrichment failed after {max_retries} attempts: {enrich_err}"}
            yield {"status": "  → Using minimal fallback enrichment..."}
            enriched = _default_enriched_tree(tree)

        visual_design, _ = _call_stage_with_retries(
            design_visuals, enriched, analysis, client, planner_tokens,
            max_retries=max_retries, stage_name="Stage 4 fallback (visual design)",
        )
        if visual_design:
            yield {"status": f"  → Theme: '{visual_design.theme_name}' with {len(visual_design.color_palette)} colors"}
        else:
            yield {"status": "  → Visual design returned empty, narrative composer will use defaults..."}

    yield {"status": "Stage 2/2: Composing compact narrative storyboard in parallel..."}
    for update in compose_narrative(
        enriched,
        visual_design,
        analysis,
        client,
        max_retries,
        duration_preset=duration_preset,
        token_counter=planner_tokens,
        planner_preferences=planner_preferences,
        stream_segments=True,
    ):
        if update.get("final"):
            # Attach planner token usage to the final update
            update["token_usage"] = dict(planner_tokens)
            update["model_profile"] = model_profile_summary()
        yield update
