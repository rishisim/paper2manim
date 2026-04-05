"""
Golden Reference Scenes for LLM Context Injection.
These are high-quality, 3Blue1Brown-style Manim scenes that demonstrate
advanced animations, precise timing, and good aesthetic practices.
"""

from functools import lru_cache

GOLDEN_SCENES = {
    "TransformMatchingTex_Example": '''
class TransformEquation(Scene):
    """
    Demonstrates how to fluidly transform one equation into another
    using TransformMatchingTex, which maps matching substrings automatically.
    """
    def construct(self):
        self.camera.background_color = "#141414"

        # Step 1: Initial Equation
        eq1 = MathTex("a^2", "+", "b^2", "=", "c^2")
        self.play(Write(eq1), run_time=2.0)
        self.wait(1.0)

        # Step 2: Transformed Equation
        # Notice we keep the exact same substrings ("a^2", "=", "c^2", "-")
        # to allow TransformMatchingTex to map them perfectly.
        eq2 = MathTex("a^2", "=", "c^2", "-", "b^2")

        # Transform matching parts to their new positions
        self.play(TransformMatchingTex(eq1, eq2), run_time=1.5)
        self.wait(1.5)

        # Step 3: Highlight the negative part
        frame = SurroundingRectangle(eq2[3:], color=YELLOW, buff=0.1)
        self.play(Create(frame))
        self.wait(2.0)
''',

    "AnimationGroup_LaggedStart_Example": '''
class MatrixTransformation(Scene):
    """
    Demonstrates applying a matrix transformation to a grid and vectors,
    using AnimationGroup and LaggedStart for elegant overlapping animations.
    """
    def construct(self):
        self.camera.background_color = "#141414"

        plane = NumberPlane(
            x_range=[-5, 5], y_range=[-5, 5],
            background_line_style={"stroke_opacity": 0.4}
        )

        v1 = Vector([1, 0], color=GREEN)
        v2 = Vector([0, 1], color=RED)

        # Elegant intro using LaggedStart
        self.play(
            LaggedStart(
                Create(plane),
                GrowArrow(v1),
                GrowArrow(v2),
                lag_ratio=0.5
            ),
            run_time=3.0
        )
        self.wait(1.0)

        # Define the matrix
        matrix = [[2, 1], [-1, 1]]

        # Apply the transformation to the plane and vectors simultaneously
        self.play(
            AnimationGroup(
                plane.animate.apply_matrix(matrix),
                v1.animate.apply_matrix(matrix),
                v2.animate.apply_matrix(matrix)
            ),
            run_time=2.5,
            rate_func=smooth
        )
        self.wait(2.0)
''',

    "Custom_ValueTracker_Example": '''
class MovingProjection(Scene):
    """
    Demonstrates using a ValueTracker to dynamically update
    a scene element (like a rotating line and its projection label)
    every single frame.
    """
    def construct(self):
        self.camera.background_color = "#141414"

        axes = Axes(x_range=[-3, 3], y_range=[-3, 3])

        # A tracker that holds a changing number (e.g. an angle)
        angle_tracker = ValueTracker(0)

        # Creates a line that updates whenever angle_tracker changes
        rotating_line = always_redraw(
            lambda: Line(
                ORIGIN,
                [2 * np.cos(angle_tracker.get_value()), 2 * np.sin(angle_tracker.get_value()), 0],
                color=BLUE
            )
        )

        # Dynamic label attached to the tip
        label = always_redraw(
            lambda: DecimalNumber(
                angle_tracker.get_value() * 180 / PI,
                num_decimal_places=0
            ).next_to(rotating_line.get_end(), UP)
        )

        self.play(Create(axes), Create(rotating_line), Write(label))
        self.wait(0.5)

        # Animate the tracker to PI (180 degrees).
        # The always_redraw elements will automatically update frame-by-frame.
        self.play(
            angle_tracker.animate.set_value(PI),
            run_time=4.0,
            rate_func=there_and_back
        )
        self.wait(1.0)
'''
}

# Cache the full golden-scenes output.  GOLDEN_SCENES is a module-level
# constant so the formatted string never changes; maxsize=1 is sufficient.
@lru_cache(maxsize=1)
def fetch_golden_scenes() -> str:
    """
    Returns several high-quality 'golden' Manim code examples
    to serve as inspiration for animations, timing, and properties.
    """
    out = ["=== GOLDEN REFERENCE SCENES ===\n"]
    out.append("Use these concepts (TransformMatchingTex, LaggedStart, always_redraw, ValueTracker) to make your output fluid and high-quality.\n")

    for name, code in GOLDEN_SCENES.items():
        out.append(f"--- Example: {name} ---")
        out.append(code.strip())
        out.append("\n")

    return "\n".join(out)
