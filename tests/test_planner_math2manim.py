import json

from agents.planner import ProSegmentedStoryboard
from agents.planner_math2manim import (
    ConceptAnalysis,
    EnrichedNode,
    EnrichedTree,
    PlanningBlueprint,
    SegmentNarrativeDraft,
    VisualDesign,
    _blueprint_to_enriched_tree,
    _blueprint_to_visual_design,
    _compose_segment_batch,
    _compose_single_segment,
    _draft_to_segment_dict,
    _friendly_planner_error,
    _planner_preference_context,
    compose_narrative,
)


def test_concept_analysis_accepts_short_preset_segment_count():
    analysis = ConceptAnalysis.model_validate({
        "core_concept": "Dot product",
        "domain": "Linear Algebra",
        "target_audience": "Undergraduate",
        "key_insights": ["Projection as directional agreement"],
        "common_misconceptions": ["Confusing dot with cross product"],
        "narrative_arc": "intuition -> formula -> application",
        "suggested_segment_count": 2,
    })
    assert analysis.suggested_segment_count == 2


def test_friendly_planner_error_maps_common_auth_failure():
    msg = _friendly_planner_error("AuthenticationError: invalid x-api-key")
    assert "ANTHROPIC_API_KEY" in msg


def test_friendly_planner_error_maps_literal_validation_noise():
    msg = _friendly_planner_error(
        "3 validation errors for PlanningBlueprint\nsegments.0.complexity\n  Input should be 'simple' or 'complex' [type=literal_error]\nhttps://errors.pydantic.dev/2.12/v/literal_error"
    )
    assert "schema mismatch" in msg
    assert "pydantic.dev" not in msg


def test_complexity_normalization_accepts_moderate_alias():
    node = EnrichedNode.model_validate({
        "id": 1,
        "title": "Setup",
        "description": "desc",
        "complexity": "moderate",
        "equations_latex": [],
        "variable_definitions": {},
        "elements": [],
        "visual_metaphor": "",
    })
    assert node.complexity == "medium"


def test_planner_preference_context_mentions_new_quality_controls():
    enriched, prompt = _planner_preference_context(
        {
            "video_length": "Medium (3-5 min)",
            "target_audience": "General audience",
            "visual_style": "Geometric intuition",
            "pacing": "Slow and exploratory",
            "quality_mode": "polished",
            "narration_style": "intuitive",
        },
        {"target_seconds": 210},
    )
    assert "Quality mode: polished" in enriched
    assert "Maximum visual density: low" in enriched
    assert "stable, meaningful frame" in prompt


def test_draft_to_segment_dict_renders_beats_into_visual_instructions():
    draft = SegmentNarrativeDraft.model_validate({
        "id": 1,
        "title": "Intro",
        "learning_goal": "Understand the setup",
        "must_show": ["axes"],
        "end_state": "axes remain visible",
        "carry_over_from_previous": "clean reset",
        "visual_density": "low",
        "scene_strategy": "clean_reset",
        "render_risk": "low",
        "expensive_features_allowed": False,
        "final_anchor_required": "axes remain visible",
        "equations_latex": [],
        "variable_definitions": {},
        "elements": ["axes"],
        "element_colors": {"axes": "#00AAFF"},
        "animations": ["Create"],
        "layout_instructions": "Axes centered",
        "beats": [
            {
                "start_s": 0,
                "end_s": 5,
                "goal": "Introduce the axes",
                "objects": ["axes"],
                "animation_intent": "Create the axes and hold briefly",
                "cleanup": [],
                "audio_cue": "Let's start with the coordinate plane",
            }
        ],
        "audio_script": "Let's start with the coordinate plane.",
        "duration_hint_seconds": 5,
        "complexity": "simple",
    })

    segment = _draft_to_segment_dict(draft)
    assert "beats" not in segment
    assert "BEAT 1 [0s–5s]:" in segment["visual_instructions"]
    assert "ANIMATION INTENT: Create the axes and hold briefly" in segment["visual_instructions"]


def test_compose_single_segment_converts_compact_draft_to_pro_shape(monkeypatch):
    compact_draft = {
        "id": 1,
        "title": "Foundations",
        "learning_goal": "Set up the core idea",
        "must_show": ["number line"],
        "end_state": "number line stays on screen",
        "carry_over_from_previous": "clean reset",
        "visual_density": "low",
        "scene_strategy": "diagram_then_equation",
        "render_risk": "low",
        "expensive_features_allowed": False,
        "final_anchor_required": "number line stays on screen",
        "equations_latex": [],
        "variable_definitions": {},
        "elements": ["number line"],
        "element_colors": {"number line": "#00AAFF"},
        "animations": ["Create"],
        "layout_instructions": "Number line centered",
        "beats": [
            {
                "start_s": 0,
                "end_s": 4,
                "goal": "Introduce the diagram",
                "objects": ["number line"],
                "animation_intent": "Reveal the number line cleanly",
                "cleanup": [],
                "audio_cue": "Start with a simple geometric picture",
            }
        ],
        "audio_script": "Start with a simple geometric picture.",
        "duration_hint_seconds": 4,
        "complexity": "simple",
    }

    monkeypatch.setattr(
        "agents.planner_math2manim._call_llm",
        lambda prompt, **kwargs: json.dumps(compact_draft),
    )

    node = EnrichedNode.model_validate({
        "id": 1,
        "title": "Foundations",
        "description": "Background",
        "complexity": "simple",
        "equations_latex": [],
        "variable_definitions": {},
        "elements": ["number line"],
        "visual_metaphor": "A path",
    })
    tree = EnrichedTree(nodes=[node])
    segment = _compose_single_segment(
        node,
        0,
        1,
        None,
        None,
        tree,
        None,
        max_retries=1,
        per_segment_seconds=4,
        token_counter=None,
        planner_preferences="",
    )

    storyboard = ProSegmentedStoryboard.model_validate({
        "theme_name": "Classic 3b1b",
        "color_palette": {"Background": "#141414", "Primary": "#00AAFF"},
        "segments": [segment],
    })
    assert storyboard.segments[0].visual_instructions.startswith("BEAT 1")


def test_compose_narrative_regeneration_only_keeps_closer_word_counts(monkeypatch):
    def build_segment(node_id: int, word_count: int) -> dict:
        return {
            "id": node_id,
            "title": f"Segment {node_id}",
            "learning_goal": "Teach one thing",
            "must_show": [f"obj{node_id}"],
            "end_state": f"obj{node_id} remains",
            "carry_over_from_previous": "clean reset",
            "visual_density": "low",
            "scene_strategy": "clean_reset",
            "render_risk": "low",
            "expensive_features_allowed": False,
            "final_anchor_required": f"obj{node_id} remains",
            "equations_latex": [],
            "variable_definitions": {},
                "elements": [f"obj{node_id}"],
                "element_colors": {f"obj{node_id}": "#00AAFF"},
                "animations": ["Create"],
                "layout_instructions": "Centered",
                "visual_instructions": "BEAT 1 [0s–40s]:\n  GOAL: demo",
                "audio_script": "word " * word_count,
                "duration_hint_seconds": 50,
                "complexity": "simple",
            }

    retry_calls = {1: 0, 2: 0}

    def fake_batch(indices, enriched_tree, *args, **kwargs):
        return {
            idx: build_segment(enriched_tree.nodes[idx].id, 30 if enriched_tree.nodes[idx].id == 1 else 200)
            for idx in indices
        }

    def fake_retry(node, segment_index, *args, **kwargs):
        retry_calls[node.id] += 1
        if node.id == 1:
            return build_segment(node.id, 110)
        return build_segment(node.id, 220)

    monkeypatch.setattr("agents.planner_math2manim._compose_segment_batch", fake_batch)
    monkeypatch.setattr("agents.planner_math2manim._compose_single_segment", fake_retry)

    tree = EnrichedTree(nodes=[
        EnrichedNode.model_validate({
            "id": 1,
            "title": "One",
            "description": "First",
            "complexity": "simple",
            "equations_latex": [],
            "variable_definitions": {},
            "elements": [],
            "visual_metaphor": "",
        }),
        EnrichedNode.model_validate({
            "id": 2,
            "title": "Two",
            "description": "Second",
            "complexity": "simple",
            "equations_latex": [],
            "variable_definitions": {},
            "elements": [],
            "visual_metaphor": "",
        }),
    ])
    visual_design = VisualDesign.model_validate({
        "theme_name": "Classic 3b1b",
        "color_palette": {"Background": "#141414", "Primary": "#00AAFF"},
        "typography_notes": "Default",
        "segment_designs": [],
    })

    updates = list(
        compose_narrative(
            tree,
            visual_design,
            None,
            None,
            max_retries=1,
            duration_preset={"per_segment_seconds": 50, "target_seconds": 100},
            token_counter=None,
            planner_preferences="",
        )
    )

    final = updates[-1]
    assert final["final"] is True
    assert len(final["storyboard"]["segments"][0]["audio_script"].split()) == 110
    assert len(final["storyboard"]["segments"][1]["audio_script"].split()) == 200
    assert retry_calls[1] == 1
    assert retry_calls[2] == 0


def test_planning_blueprint_round_trips_into_enriched_tree_and_visual_design():
    blueprint = PlanningBlueprint.model_validate({
        "analysis": {
            "core_concept": "Euler's identity",
            "domain": "Complex analysis",
            "target_audience": "Undergraduate",
            "key_insights": ["Rotation meets exponentials"],
            "common_misconceptions": ["Imaginary numbers are not geometric"],
            "narrative_arc": "geometry -> formula -> payoff",
            "suggested_segment_count": 2,
        },
        "theme_name": "Classic 3b1b",
        "color_palette": {"Background": "#141414", "Primary": "#00AAFF"},
        "typography_notes": "Default",
        "segments": [
            {
                "id": 1,
                "title": "Foundations",
                "description": "Set up the plane",
                "complexity": "simple",
                "equations_latex": ["z = a + bi"],
                "variable_definitions": {"z": "complex number"},
                "elements": ["axes"],
                "visual_metaphor": "A point in a plane",
                "layout_blueprint": "Axes centered",
                "camera_notes": "2D static",
                "transition_in": "Clean slate",
                "transition_out": "Keep axes visible",
            },
            {
                "id": 2,
                "title": "Payoff",
                "description": "Reveal the identity",
                "complexity": "complex",
                "equations_latex": ["e^{i\\pi} + 1 = 0"],
                "variable_definitions": {"\\pi": "pi"},
                "elements": ["equation"],
                "visual_metaphor": "A perfect closure",
                "layout_blueprint": "Equation centered",
                "camera_notes": "2D static",
                "transition_in": "Carry axes into the equation reveal",
                "transition_out": "Hold final identity",
            },
        ],
    })

    enriched = _blueprint_to_enriched_tree(blueprint)
    visual_design = _blueprint_to_visual_design(blueprint)

    assert enriched.nodes[0].title == "Foundations"
    assert enriched.nodes[1].equations_latex == ["e^{i\\pi} + 1 = 0"]
    assert visual_design.theme_name == "Classic 3b1b"
    assert visual_design.segment_designs[1].transition_out == "Hold final identity"


def test_compose_narrative_streams_completed_segments(monkeypatch):
    segment = {
        "id": 1,
        "title": "Segment 1",
        "learning_goal": "Teach one thing",
        "must_show": ["obj1"],
        "end_state": "obj1 remains",
        "carry_over_from_previous": "clean reset",
        "visual_density": "low",
        "scene_strategy": "clean_reset",
        "render_risk": "low",
        "expensive_features_allowed": False,
        "final_anchor_required": "obj1 remains",
        "equations_latex": [],
        "variable_definitions": {},
        "elements": ["obj1"],
        "element_colors": {"obj1": "#00AAFF"},
        "animations": ["Create"],
        "layout_instructions": "Centered",
        "visual_instructions": "BEAT 1 [0s–5s]:\n  GOAL: demo",
        "audio_script": "word " * 80,
        "duration_hint_seconds": 50,
        "complexity": "simple",
    }

    monkeypatch.setattr(
        "agents.planner_math2manim._compose_segment_batch",
        lambda indices, *args, **kwargs: {indices[0]: dict(segment)},
    )

    tree = EnrichedTree(nodes=[
        EnrichedNode.model_validate({
            "id": 1,
            "title": "One",
            "description": "First",
            "complexity": "simple",
            "equations_latex": [],
            "variable_definitions": {},
            "elements": [],
            "visual_metaphor": "",
        })
    ])
    visual_design = VisualDesign.model_validate({
        "theme_name": "Classic 3b1b",
        "color_palette": {"Background": "#141414", "Primary": "#00AAFF"},
        "typography_notes": "Default",
        "segment_designs": [],
    })

    updates = list(
        compose_narrative(
            tree,
            visual_design,
            None,
            None,
            max_retries=1,
            duration_preset={"per_segment_seconds": 50, "target_seconds": 50},
            token_counter=None,
            planner_preferences="",
            stream_segments=True,
        )
    )

    partial = next(update for update in updates if update.get("segment_storyboard"))
    assert partial["segment_storyboard"]["title"] == "Segment 1"
    assert partial["theme_name"] == "Classic 3b1b"


def test_compose_narrative_uses_adjacent_pair_batches(monkeypatch):
    batch_calls: list[tuple[int, ...]] = []

    def build_segment(node_id: int) -> dict:
        return {
            "id": node_id,
            "title": f"Segment {node_id}",
            "learning_goal": "Teach one thing",
            "must_show": [f"obj{node_id}"],
            "end_state": f"obj{node_id} remains",
            "carry_over_from_previous": "clean reset",
            "visual_density": "low",
            "scene_strategy": "clean_reset",
            "render_risk": "low",
            "expensive_features_allowed": False,
            "final_anchor_required": f"obj{node_id} remains",
            "equations_latex": [],
            "variable_definitions": {},
            "elements": [f"obj{node_id}"],
            "element_colors": {f"obj{node_id}": "#00AAFF"},
            "animations": ["Create"],
            "layout_instructions": "Centered",
            "visual_instructions": "BEAT 1 [0s–5s]:\n  GOAL: demo",
            "audio_script": "word " * 100,
            "duration_hint_seconds": 50,
            "complexity": "simple",
        }

    def fake_batch(indices, enriched_tree, *args, **kwargs):
        batch_calls.append(tuple(indices))
        return {idx: build_segment(enriched_tree.nodes[idx].id) for idx in indices}

    monkeypatch.setattr("agents.planner_math2manim._compose_segment_batch", fake_batch)

    tree = EnrichedTree(nodes=[
        EnrichedNode.model_validate({
            "id": i,
            "title": f"Segment {i}",
            "description": "Desc",
            "complexity": "simple",
            "equations_latex": [],
            "variable_definitions": {},
            "elements": [],
            "visual_metaphor": "",
        })
        for i in range(1, 5)
    ])
    visual_design = VisualDesign.model_validate({
        "theme_name": "Classic 3b1b",
        "color_palette": {"Background": "#141414", "Primary": "#00AAFF"},
        "typography_notes": "Default",
        "segment_designs": [],
    })

    updates = list(
        compose_narrative(
            tree,
            visual_design,
            None,
            None,
            max_retries=1,
            duration_preset={"per_segment_seconds": 50, "target_seconds": 200},
            token_counter=None,
            planner_preferences="",
        )
    )

    assert updates[-1]["final"] is True
    assert set(batch_calls) == {(0, 1), (2, 3)}


def test_compose_segment_batch_falls_back_to_individual_segments(monkeypatch):
    fallback_calls: list[int] = []

    monkeypatch.setattr("agents.planner_math2manim._call_llm", lambda *args, **kwargs: "{not json")

    def fake_single(node, segment_index, *args, **kwargs):
        fallback_calls.append(node.id)
        return {
            "id": node.id,
            "title": node.title,
            "learning_goal": "Teach one thing",
            "must_show": [f"obj{node.id}"],
            "end_state": f"obj{node.id} remains",
            "carry_over_from_previous": "clean reset",
            "visual_density": "low",
            "scene_strategy": "clean_reset",
            "render_risk": "low",
            "expensive_features_allowed": False,
            "final_anchor_required": f"obj{node.id} remains",
            "equations_latex": [],
            "variable_definitions": {},
            "elements": [f"obj{node.id}"],
            "element_colors": {f"obj{node.id}": "#00AAFF"},
            "animations": ["Create"],
            "layout_instructions": "Centered",
            "visual_instructions": "BEAT 1 [0s–5s]:\n  GOAL: demo",
            "audio_script": "word " * 100,
            "duration_hint_seconds": 50,
            "complexity": "simple",
        }

    monkeypatch.setattr("agents.planner_math2manim._compose_single_segment", fake_single)

    tree = EnrichedTree(nodes=[
        EnrichedNode.model_validate({
            "id": 1,
            "title": "One",
            "description": "First",
            "complexity": "simple",
            "equations_latex": [],
            "variable_definitions": {},
            "elements": [],
            "visual_metaphor": "",
        }),
        EnrichedNode.model_validate({
            "id": 2,
            "title": "Two",
            "description": "Second",
            "complexity": "simple",
            "equations_latex": [],
            "variable_definitions": {},
            "elements": [],
            "visual_metaphor": "",
        }),
    ])

    result = _compose_segment_batch(
        [0, 1],
        tree,
        None,
        None,
        None,
        max_retries=1,
        per_segment_seconds=50,
        token_counter=None,
        planner_preferences="",
    )

    assert fallback_calls == [1, 2]
    assert result[0]["title"] == "One"
    assert result[1]["title"] == "Two"
