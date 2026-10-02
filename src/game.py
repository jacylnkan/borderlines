"""Session state and scoring for single-player and pass-the-device rounds."""

from copy import deepcopy
from typing import cast
from uuid import uuid4

import streamlit as st

from src.data.countries import filter_landmasses
from src.preprocessing.drawing import drawing_to_mask
from src.preprocessing.masks import country_to_mask, create_overlay
from src.scoring.scoring import score_with_difficulty
from src.utils.models import Drawing, Game, LandGeometry, RoundSettings, Submission


def start_game(players: list[str]) -> None:
    """Start a fresh session game; two players begin at a turn announcement."""
    game: Game = {
        "id": uuid4().hex,
        "players": players,
        "turn": 0,
        "stage": "turn" if len(players) == 2 else "canvas",
        "submissions": [],
        "round_settings": None,
    }
    st.session_state["game"] = game
    st.session_state.pop("submission", None)


def get_game() -> Game | None:
    """Return the active game, or None until a mode has been selected."""
    return cast(Game | None, st.session_state.get("game"))


def reset_game() -> None:
    """Clear the current game and mode choice so the welcome modal opens again."""
    for key in ("game", "submission", "welcome_mode"):
        st.session_state.pop(key, None)


def score_submission(
    drawing: Drawing,
    geometry: LandGeometry,
    country_name: str,
    settings: RoundSettings,
) -> Submission:
    """Process both outlines and capture a score, breakdown, and matching overlay."""
    area_ratio = settings["landmass_cutoff"] / 100
    drawing_mask = drawing_to_mask(drawing, min_area_ratio=area_ratio)
    country_mask = country_to_mask(filter_landmasses(geometry, area_ratio))
    comparison = score_with_difficulty(drawing_mask, country_mask, **settings["difficulty"])
    return {
        "country_code": settings["country_code"],
        "country_name": country_name,
        "drawing": deepcopy(drawing),
        "score": comparison["breakdown"]["score"],
        "score_breakdown": comparison["breakdown"],
        "landmass_cutoff": settings["landmass_cutoff"],
        "difficulty": settings["difficulty"].copy(),
        "rotation_degrees": comparison["rotation_degrees"],
        "overlay": create_overlay(comparison["drawing_mask"], comparison["country_mask"]),
    }


def save_submission(game: Game, submission: Submission, settings: RoundSettings) -> None:
    """Save a solo result or advance multiplayer to the next handoff/results screen."""
    if len(game["players"]) == 1:
        st.session_state["submission"] = submission
        return
    submission["player_name"] = game["players"][game["turn"]]
    game["submissions"].append(submission)
    game["round_settings"] = deepcopy(settings)
    st.session_state.pop("submission", None)
    if game["turn"] == 0:
        game["turn"] = 1
        game["stage"] = "turn"
    else:
        game["stage"] = "results"
