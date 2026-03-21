import json
import re
from typing import Iterator, Literal, List, Dict
from pydantic import BaseModel, Field, ValidationError
from google import genai

class ConceptNode(BaseModel):
    id: int
    title: str = Field(description="Title of the concept/segment.")
    description: str = Field(description="What this concept is about and why it is a prerequisite.")
    complexity: Literal["simple", "complex"] = Field(default="complex")

class PrerequisiteTree(BaseModel):
    nodes: List[ConceptNode] = Field(min_length=1, description="Ordered list of prerequisites leading up to the target concept.")

class EnrichedNode(BaseModel):
    id: int
    # Inherited from ConceptNode roughly
    title: str
    description: str
    complexity: Literal["simple", "complex"]
    # Math & Visuals
    equations_latex: List[str] = Field(description="Raw LaTeX strings (double backslashes)")
    variable_definitions: Dict[str, str] = Field(description="Maps LaTeX symbols to physical/math meanings")
    elements: List[str] = Field(description="Visual objects like 'graph', 'axes', 'triangle'")
    visual_metaphor: str = Field(description="A metaphor for how this concept is visualized (e.g., 'a photon sliding down a gravity well')")

class EnrichedTree(BaseModel):
    nodes: List[EnrichedNode]

def _extract_json_text(raw_text: str) -> str:
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        # Fallback to finding something that looks like an array if that's requested
        match_arr = re.search(r"\[.*\]", text, re.DOTALL)
        if match_arr:
            return match_arr.group(0)
    return match.group(0) if match else text

def build_prerequisite_tree(concept: str, client: genai.Client) -> PrerequisiteTree | None:
    prompt = f"""
You are an expert pedagogical planner. The user wants to learn about: "{concept}"
We need to build a Reverse Knowledge Tree.
Ask yourself: "What must someone understand BEFORE they can understand {concept}?"
Trace this recursively down to foundational math/physics/CS topics.
Then, reverse the order to explicitly list the sequence of segments from Foundational up to "{concept}".
Output as JSON matching this schema:
{{
  "nodes": [
    {{
      "id": 1,
      "title": "...",
      "description": "...",
      "complexity": "simple" | "complex"
    }}
  ]
}}
"""
    try:
        response = client.models.generate_content(model="gemini-3.1-pro-preview", contents=prompt)
        text = _extract_json_text(response.text or "")
        return PrerequisiteTree.model_validate(json.loads(text))
    except Exception as e:
        print(f"Failed to build prerequisite tree: {e}")
        return None

def enrich_concept_tree(tree: PrerequisiteTree, client: genai.Client) -> EnrichedTree | None:
    prompt = f"""
You are an expert mathematical enricher and visual designer.
Here is the sequence of concepts we are teaching:
{json.dumps(tree.model_dump(), indent=2)}

For each concept node, enrich it with:
1. Strict, correct LaTeX equations that govern it.
2. Variable definitions for those equations.
3. The primitive visual outline (elements to draw, like vectors, graphs).
4. A creative visual metaphor that connects the math to intuition (e.g., 'water flowing through pipes').

Output as JSON matching this schema:
{{
  "nodes": [
    {{
      "id": 1,
      "title": "...",
      "description": "...",
      "complexity": "...",
      "equations_latex": ["..."],
      "variable_definitions": {{"symbol": "meaning"}},
      "elements": ["..."],
      "visual_metaphor": "..."
    }}
  ]
}}
"""
    try:
        response = client.models.generate_content(model="gemini-3.1-pro-preview", contents=prompt)
        text = _extract_json_text(response.text or "")
        return EnrichedTree.model_validate(json.loads(text))
    except Exception as e:
        print(f"Failed to enrich tree: {e}")
        return None

def compile_storyboard(enriched_tree: EnrichedTree, client: genai.Client, max_retries: int = 3) -> Iterator[dict]:
    prompt = f"""
You are an expert cinematic director and Manim narrative composer.
We have planned out a sequence of mathematically rigorous video segments:

{json.dumps(enriched_tree.model_dump(), indent=2)}

Please write the final VERBOSE storyboard. Output as JSON matching this schema exactly:
{{
  "theme_name": "e.g. 'Classic 3b1b'",
  "color_palette": {{"Element": "#HEXCODE"}},
  "segments": [
    {{
      "id": 1,
      "title": "...",
      "equations_latex": ["..."],
      "variable_definitions": {{"symbol": "meaning"}},
      "elements": ["..."],
      "element_colors": {{"element": "#HEXCODE"}},
      "animations": ["TransformMatchingTex", "Create", "..."],
      "layout_instructions": "...",
      "visual_instructions": "VERY SPECIFIC, STEP-BY-STEP chronological narrative of the scene...",
      "audio_script": "Engaging voiceover script",
      "duration_hint_seconds": 60,
      "complexity": "simple" | "complex"
    }}
  ]
}}
"""
    last_error = ""
    for attempt in range(max_retries):
        yield {"status": f"Drafting Final PRO Storyboard (Attempt {attempt + 1})..."}
        try:
            response = client.models.generate_content(model="gemini-3.1-pro-preview", contents=prompt)
            text = _extract_json_text(response.text or "")
            from agents.planner import ProSegmentedStoryboard # lazy import
            payload = json.loads(text)
            storyboard = ProSegmentedStoryboard.model_validate(payload)
            yield {"final": True, "storyboard": storyboard.model_dump()}
            return
        except Exception as e:
            last_error = str(e)
            yield {"status": f"Validation failed ({last_error}), retrying..."}
            
    yield {"final": True, "error": f"Failed to compile storyboard: {last_error}"}

def run_math2manim_planner(concept: str, max_retries: int = 3, previous_storyboard: dict | None = None, feedback: str | None = None) -> Iterator[dict]:
    client = genai.Client()
    
    # We skip tree building if we already had a previous storyboard and feedback... wait, 
    # actually let's just make it purely fresh if no previous storyboard, else we can just do one pass.
    # But for now let's just run the full pipeline.
    
    yield {"status": "Agent 1: Building Prerequisite Knowledge Tree..."}
    tree = build_prerequisite_tree(concept, client)
    if not tree:
        yield {"final": True, "error": "Agent 1 failed to build knowledge tree."}
        return
        
    yield {"status": f"Agent 2: Enriching {len(tree.nodes)} segments with Math and Visual Metaphors..."}
    enriched = enrich_concept_tree(tree, client)
    if not enriched:
        yield {"final": True, "error": "Agent 2 failed to enrich the knowledge tree."}
        return
        
    for update in compile_storyboard(enriched, client, max_retries):
        yield update
