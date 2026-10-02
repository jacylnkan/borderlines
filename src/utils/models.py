"""Shared types for drawings, scores, and session state."""

from typing import Any, Literal, NotRequired, TypeAlias, TypedDict

import numpy as np
from numpy.typing import NDArray
from shapely.geometry import MultiPolygon, Polygon

LandGeometry: TypeAlias = Polygon | MultiPolygon
Mask: TypeAlias = NDArray[np.bool_]
Points: TypeAlias = NDArray[np.float64]
Image: TypeAlias = NDArray[np.uint8]
Drawing: TypeAlias = dict[str, Any]


class Difficulty(TypedDict):
    allow_rotation: bool
    rounding: float


class RoundSettings(TypedDict):
    country_code: str
    landmass_cutoff: int
    difficulty: Difficulty


class ScoreBreakdown(TypedDict):
    score: float
    area_overlap: float
    border_match: float
    contour_similarity: float


class Comparison(TypedDict):
    breakdown: ScoreBreakdown
    drawing_mask: Mask
    country_mask: Mask
    rotation_degrees: float


class Submission(TypedDict):
    country_code: str
    country_name: str
    drawing: Drawing
    score: float
    score_breakdown: ScoreBreakdown
    landmass_cutoff: int
    difficulty: Difficulty
    rotation_degrees: float
    overlay: Image
    player_name: NotRequired[str]


class Game(TypedDict):
    id: str
    players: list[str]
    turn: int
    stage: Literal["turn", "canvas", "results"]
    submissions: list[Submission]
    round_settings: RoundSettings | None


class CanvasSettings(TypedDict):
    stroke_width: int
