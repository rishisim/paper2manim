from agents.planner_math2manim import (
    ConceptAnalysis,
    _friendly_planner_error,
    _planner_preference_context,
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
