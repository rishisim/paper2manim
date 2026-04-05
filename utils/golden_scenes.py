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
''',

    "Graph_Network_Example": '''
class GraphTraversal(Scene):
    """
    Demonstrates building a graph with labeled vertices and edges,
    then animating a BFS traversal with color highlighting.
    """
    def construct(self):
        self.camera.background_color = "#141414"

        # Define vertices and edges
        vertices = [1, 2, 3, 4, 5]
        edges = [(1, 2), (1, 3), (2, 4), (3, 4), (3, 5)]
        layout = {1: [-2, 1, 0], 2: [0, 2, 0], 3: [0, 0, 0], 4: [2, 1, 0], 5: [2, -1, 0]}

        g = Graph(
            vertices, edges,
            layout=layout,
            labels=True,
            vertex_config={"radius": 0.3, "fill_color": BLUE, "fill_opacity": 0.8},
            edge_config={"stroke_color": GREY_B, "stroke_width": 2},
        )

        self.play(Create(g), run_time=2.0)
        self.wait(1.0)

        # BFS traversal: highlight visited nodes and edges
        bfs_order = [1, 2, 3, 4, 5]
        bfs_edges = [(1, 2), (1, 3), (2, 4), (3, 5)]
        for v in bfs_order:
            self.play(
                g.vertices[v].animate.set_fill(YELLOW, opacity=1.0),
                run_time=0.6,
            )
            self.wait(0.3)

        for u, v in bfs_edges:
            self.play(
                g.edges[(u, v)].animate.set_stroke(YELLOW, width=4),
                run_time=0.5,
            )
        self.wait(2.0)
''',

    "MovingCamera_Zoom_Example": '''
class CameraZoomScene(MovingCameraScene):
    """
    Demonstrates camera zooming and panning using MovingCameraScene.
    Shows a wide view, then zooms into a detail.
    """
    def construct(self):
        self.camera.background_color = "#141414"

        # Create a number plane with several objects
        plane = NumberPlane(x_range=[-8, 8], y_range=[-5, 5])
        circle = Circle(radius=0.5, color=YELLOW, fill_opacity=0.8).move_to([4, 3, 0])
        label = MathTex(r"P").next_to(circle, UP, buff=0.2)
        square = Square(side_length=1, color=GREEN, fill_opacity=0.5).move_to([-3, -2, 0])

        self.play(Create(plane), run_time=1.5)
        self.play(
            LaggedStart(Create(circle), Write(label), Create(square), lag_ratio=0.4),
            run_time=2.0,
        )
        self.wait(1.0)

        # Zoom into the circle
        self.play(
            self.camera.frame.animate.set(width=4).move_to(circle),
            run_time=2.0,
            rate_func=smooth,
        )
        self.wait(1.5)

        # Zoom back out
        self.play(
            self.camera.frame.animate.set(width=14).move_to(ORIGIN),
            run_time=2.0,
            rate_func=smooth,
        )
        self.wait(1.0)
''',

    "StepByStep_Proof_Example": '''
class ProofDerivation(Scene):
    """
    Demonstrates a step-by-step algebraic derivation with labels
    explaining each transformation.
    """
    def construct(self):
        self.camera.background_color = "#141414"

        title = Text("Completing the Square", font_size=42, color=YELLOW).to_edge(UP, buff=0.5)
        self.play(Write(title), run_time=1.0)
        self.wait(0.5)

        # Step 1: Start equation
        eq1 = MathTex("x^2", "+", "6x", "+", "5", "=", "0")
        eq1.move_to(ORIGIN)
        self.play(Write(eq1), run_time=1.5)
        self.wait(1.0)

        # Step 2: Move constant
        eq2 = MathTex("x^2", "+", "6x", "=", "-5")
        label1 = Text("Move constant to RHS", font_size=22, color=GREY_B).next_to(eq2, DOWN, buff=0.6)
        self.play(TransformMatchingTex(eq1, eq2), run_time=1.5)
        self.play(FadeIn(label1, shift=UP * 0.2), run_time=0.6)
        self.wait(1.0)

        # Step 3: Add (b/2)^2 to both sides
        eq3 = MathTex("x^2", "+", "6x", "+", "9", "=", "-5", "+", "9")
        self.play(FadeOut(label1), run_time=0.3)
        label2 = Text("Add (6/2)^2 = 9 to both sides", font_size=22, color=GREY_B).next_to(eq3, DOWN, buff=0.6)
        self.play(TransformMatchingTex(eq2, eq3), run_time=1.5)
        self.play(FadeIn(label2, shift=UP * 0.2), run_time=0.6)
        self.wait(1.0)

        # Step 4: Factor
        eq4 = MathTex("(x + 3)^2", "=", "4")
        self.play(FadeOut(label2), run_time=0.3)
        label3 = Text("Factor left side, simplify right", font_size=22, color=GREY_B).next_to(eq4, DOWN, buff=0.6)
        self.play(TransformMatchingTex(eq3, eq4), run_time=1.5)
        self.play(FadeIn(label3, shift=UP * 0.2), run_time=0.6)
        self.wait(2.0)
''',

    "MoveAlongPath_Example": '''
class DotOnCurve(Scene):
    """
    Demonstrates a dot moving along a parametric curve with a traced path
    and a dynamic tangent line.
    """
    def construct(self):
        self.camera.background_color = "#141414"

        axes = Axes(x_range=[-1, 7, 1], y_range=[-2, 4, 1], x_length=8, y_length=5)
        curve = axes.plot(lambda x: np.sin(x) + 1, x_range=[0, 2 * PI], color=BLUE)

        self.play(Create(axes), run_time=1.5)
        self.play(Create(curve), run_time=2.0)
        self.wait(0.5)

        # Dot that will travel along the curve
        dot = Dot(color=YELLOW).move_to(curve.get_start())
        traced = TracedPath(dot.get_center, stroke_color=RED, stroke_width=3)

        self.add(traced)
        self.play(FadeIn(dot, scale=0.5), run_time=0.5)

        # Move the dot along the full curve
        self.play(MoveAlongPath(dot, curve), run_time=4.0, rate_func=linear)
        self.wait(1.0)

        # Highlight the traced path
        self.play(traced.animate.set_stroke(opacity=0.4), run_time=0.8)
        self.wait(1.5)
''',

    "Matrix_Highlight_Example": '''
class MatrixOperations(Scene):
    """
    Demonstrates displaying a matrix with bracket notation and
    highlighting specific elements or rows.
    """
    def construct(self):
        self.camera.background_color = "#141414"

        m = Matrix(
            [[2, -1, 0], [3, 4, -2], [1, 0, 5]],
            left_bracket="[",
            right_bracket="]",
        ).scale(0.9)
        m_label = MathTex("A", "=").next_to(m, LEFT, buff=0.3)

        self.play(Write(m_label), Write(m), run_time=2.0)
        self.wait(1.0)

        # Highlight the diagonal
        entries = m.get_entries()
        diag_indices = [0, 4, 8]  # (0,0), (1,1), (2,2)
        highlights = VGroup(*[
            SurroundingRectangle(entries[i], color=YELLOW, buff=0.1) for i in diag_indices
        ])
        self.play(LaggedStart(*[Create(h) for h in highlights], lag_ratio=0.3), run_time=1.5)
        self.wait(0.5)

        trace_label = MathTex(r"\\text{tr}(A) = 2 + 4 + 5 = 11", color=YELLOW)
        trace_label.to_edge(DOWN, buff=0.5)
        self.play(Write(trace_label), run_time=1.5)
        self.wait(2.0)
''',

    "ColorGradient_Transform_Example": '''
class GradientMorphing(Scene):
    """
    Demonstrates color gradients on shapes and smooth morphing
    between different geometric forms.
    """
    def construct(self):
        self.camera.background_color = "#141414"

        circle = Circle(radius=1.5, fill_opacity=0.8, stroke_width=2)
        circle.set_color(color=[BLUE, GREEN, YELLOW])

        self.play(Create(circle), run_time=2.0)
        self.wait(1.0)

        # Morph circle into a square with a different gradient
        square = Square(side_length=3, fill_opacity=0.8, stroke_width=2)
        square.set_color(color=[RED, ORANGE, YELLOW])

        self.play(Transform(circle, square), run_time=2.5, rate_func=smooth)
        self.wait(1.0)

        # Morph into a triangle
        triangle = Triangle(fill_opacity=0.8, stroke_width=2).scale(2)
        triangle.set_color(color=[PURPLE, PINK, TEAL])

        self.play(Transform(circle, triangle), run_time=2.5, rate_func=smooth)
        self.wait(2.0)
''',

    "NumberLine_Annotation_Example": '''
class AnnotatedNumberLine(Scene):
    """
    Demonstrates a number line with braces, intervals, and labels
    for illustrating ranges and key points.
    """
    def construct(self):
        self.camera.background_color = "#141414"

        nl = NumberLine(x_range=[-2, 8, 1], length=10, include_numbers=True)
        self.play(Create(nl), run_time=1.5)
        self.wait(0.5)

        # Mark an interval [2, 6]
        dot_a = Dot(nl.n2p(2), color=GREEN, radius=0.12)
        dot_b = Dot(nl.n2p(6), color=GREEN, radius=0.12)
        interval_line = Line(nl.n2p(2), nl.n2p(6), color=GREEN, stroke_width=6)

        self.play(
            LaggedStart(FadeIn(dot_a, scale=0.5), Create(interval_line), FadeIn(dot_b, scale=0.5), lag_ratio=0.3),
            run_time=1.5,
        )
        self.wait(0.5)

        # Add a brace below the interval
        brace = Brace(interval_line, DOWN, color=YELLOW)
        brace_label = brace.get_tex(r"\\Delta x = 4")
        self.play(Create(brace), Write(brace_label), run_time=1.5)
        self.wait(1.0)

        # Highlight the midpoint
        mid_dot = Dot(nl.n2p(4), color=RED, radius=0.15)
        mid_label = MathTex(r"\\bar{x}", color=RED).next_to(mid_dot, UP, buff=0.3)
        self.play(FadeIn(mid_dot, scale=0.5), Write(mid_label), run_time=1.0)
        self.wait(2.0)
''',
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
    out.append(
        "Use these patterns (TransformMatchingTex, LaggedStart, always_redraw, ValueTracker, "
        "Graph, MovingCameraScene, MoveAlongPath, Matrix, color gradients, NumberLine annotations) "
        "to make your output fluid and high-quality.\n"
    )

    for name, code in GOLDEN_SCENES.items():
        out.append(f"--- Example: {name} ---")
        out.append(code.strip())
        out.append("\n")

    return "\n".join(out)
