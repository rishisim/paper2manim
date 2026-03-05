from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = "#141414"
        
        plane = NumberPlane()
        v = Vector([3, 1], color=YELLOW)
        w = Vector([2, 2], color=BLUE)
        
        self.play(Create(plane))
        self.play(Create(v), Create(w))
        
        self.wait(1)
