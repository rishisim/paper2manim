from __future__ import annotations
from enum import Enum


class Stage(str, Enum):
    """Pipeline stage identifiers.

    Inherits from str so ``Stage.PLAN == "plan"`` for JSON compat — NDJSON
    output stays unchanged and no TypeScript changes are needed.
    """

    PLAN = "plan"
    TTS = "tts"
    CODE = "code"
    CODE_RETRY = "code_retry"
    VERIFY = "verify"
    RENDER = "render"
    STITCH = "stitch"
    CONCAT = "concat"
    DONE = "done"
