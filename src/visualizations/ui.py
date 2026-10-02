"""Streamlit screens and controls; game state and scoring live in separate modules."""

from typing import cast

import streamlit as st

from src.game import reset_game, start_game
from src.utils.constants import DEFAULT_COUNTRY_CODE
from src.utils.models import CanvasSettings, Game, RoundSettings, Submission


@st.dialog(title="Welcome to BorderLines!", width="large", dismissible=False)
def show_welcome() -> None:
    """Choose solo play immediately, or collect names before starting two-player play."""
    st.write("Draw a country from memory. Play solo or take turns on the same device.")

    mode = st.segmented_control("Game mode", ["1 Player", "2 Players"], key="welcome_mode")

    if mode == "1 Player":
        start_game(["You"])
        st.rerun()
    if mode == "2 Players":
        with st.form("player_names"):
            first = st.text_input("Player 1 name", max_chars=40)
            second = st.text_input("Player 2 name", max_chars=40)
            ready = st.form_submit_button("Start game", type="primary")
        if ready:
            names = [first.strip(), second.strip()]
            if not all(names):
                st.error("Enter a name for both players.")
            elif names[0].casefold() == names[1].casefold():
                st.error("Use different names so we can tell the players apart!")
            else:
                start_game(names)
                st.rerun()


def show_game_menu() -> None:
    """Render the centered sidebar heading and New game button."""
    with st.sidebar.container(key="game_settings_heading"):
        st.subheader("Game Settings")
    with st.sidebar.container(key="new_game_button"):
        if st.button("New game"):
            reset_game()
            st.rerun()


def show_turn_screen(game: Game) -> None:
    """Announce the next player without revealing the previous player's drawing."""
    player = game["players"][game["turn"]]
    with st.container(key="turn_screen"):
        st.subheader(f"{player}, you're {'first' if game['turn'] == 0 else 'next'}!")
        if game["turn"] == 0:
            st.write(f"{player} starts, then {game['players'][1]} will draw the same country.")
            st.write("Choose your country and difficulty settings on the next screen.")
        else:
            st.write(f"Pass the device to {player}. Your drawing starts on a fresh canvas.")
            st.write("The country and difficulty settings are the same as the first turn.")
        if st.button("Start my turn", type="primary"):
            game["stage"] = "canvas"
            st.rerun()


def show_round_results(game: Game) -> None:
    """Reveal both scores and overlays, announce a winner, and offer another round."""
    first, second = game["submissions"]

    with st.container(key="round_results_winner_announcement"):
        if abs(first["score"] - second["score"]) < 0.05:
            st.header("It's a tie!")
        else:
            winner = max(game["submissions"], key=lambda result: result["score"])
            st.header(f"And the winner is... {winner['player_name']}!")
            st.balloons()

    with st.container(key="round_results_country_heading"):
        st.subheader(f"{first['country_name']}")

    for column, result in zip(st.columns(2), game["submissions"]):
        with column:
            st.subheader(result["player_name"])
            st.metric("Shape match", f"{result['score']:.1f}/100")
            st.image(result["overlay"], width="stretch")
            st.caption("Blue: country · Orange: drawing · Purple: overlap")
    if st.button("Play another round", type="primary"):
        start_game(game["players"])
        st.rerun()


def show_sidebar(
    game: Game, country_names: dict[str, str]
) -> tuple[CanvasSettings, RoundSettings]:
    """Return drawing styles and round settings; lock scoring settings for player two."""
    locked = len(game["players"]) > 1 and game["turn"] > 0
    saved = game["round_settings"]

    default_country = saved["country_code"] if saved else DEFAULT_COUNTRY_CODE
    country = st.sidebar.selectbox(
        "Country",
        options=list(country_names),
        index=list(country_names).index(default_country),
        format_func=country_names.get,
        disabled=locked,
    )

    stroke_width = st.sidebar.slider("Stroke width: ", 1, 25, 3)

    landmass_cutoff = st.sidebar.slider(
        "Minimum landmass size (%)",
        min_value=0,
        max_value=20,
        value=saved["landmass_cutoff"] if saved else 0,
        disabled=locked,
        help=(
            "Keep landmasses at least this percentage of the largest landmass's area. "
            "0 includes everything. 20 keeps landmasses at least one fifth as large."
        ),
    )

    st.sidebar.subheader("Difficulty")
    allow_rotation = st.sidebar.checkbox(
        "Allow rotations",
        value=saved["difficulty"]["allow_rotation"] if saved else False,
        disabled=locked,
        help="Try different drawing orientations and keep the highest shape-match score.",
    )
    rounding = st.sidebar.slider(
        "Coastline rounding",
        min_value=0.0,
        max_value=5.0,
        value=saved["difficulty"]["rounding"] if saved else 0.0,
        disabled=locked,
        step=0.5,
        help=(
            "0 keeps full detail. Higher values soften jagged coastlines on both shapes. "
            "Strength is measured in pixels on the 256 × 256 scoring masks."
        ),
    )

    return (
        {"stroke_width": stroke_width},
        {
            "country_code": str(country),
            "landmass_cutoff": landmass_cutoff,
            "difficulty": {"allow_rotation": allow_rotation, "rounding": rounding},
        },
    )


def show_drawing_instructions(country_name: str, settings: RoundSettings) -> None:
    """Explain multi-stroke drawing and the selected difficulty settings."""
    st.subheader(f"Draw the borders of {country_name}!")
    st.caption("Draw with your mouse. Use the canvas toolbar to undo or clear.")
    st.caption(
        "Lift your pen whenever you like and continue near a previous stroke's endpoint. "
        "Small gaps (up to 40 pixels) and accidental crossings are fixed automatically. "
        "Position and overall size do not affect the score."
    )
    st.caption(
        "Rotation matching is enabled; orientation will be adjusted for the best score."
        if settings["difficulty"]["allow_rotation"]
        else "Keep north at the top, or enable **Allow rotations** in the sidebar."
    )
    st.caption(
        f"Retains landmasses that have at least {settings['landmass_cutoff']}% of the "
        "largest landmass's area. Smaller separate landmasses in your drawing are ignored. "
        "Set the cutoff to 0 to include all land areas."
    )


def show_solo_result(settings: RoundSettings) -> None:
    """Display the last solo result, or request resubmission when settings change."""
    submission = cast(Submission | None, st.session_state.get("submission"))

    if not submission or submission["country_code"] != settings["country_code"]:
        return
    if submission["difficulty"] != settings["difficulty"]:
        st.info("Submit your drawing again to use the current difficulty settings.")
        return
    if submission["landmass_cutoff"] != settings["landmass_cutoff"]:
        st.info("Submit your drawing again to score it with the current landmass cutoff.")
        return

    st.subheader("Results")

    st.metric("Shape match", f"{submission['score']:.1f}/100")

    breakdown = submission["score_breakdown"]
    area, border, contour = st.columns(3)
    area.metric(
        "Area overlap",
        f"{breakdown['area_overlap']:.1f}/100",
        help="Intersection over union: how well the filled areas overlap.",
    )
    border.metric(
        "Border match",
        f"{breakdown['border_match']:.1f}/100",
        help="Checks both outlines for matching edges within about 7 pixels.",
    )
    contour.metric(
        "Contour similarity",
        f"{breakdown['contour_similarity']:.1f}/100",
        help="Penalizes average border distance and large errors along either outline.",
    )

    st.image(submission["overlay"], width=400)
    st.caption("Blue: actual country · Orange: your drawing · Purple: overlap")
    if settings["difficulty"]["allow_rotation"]:
        st.caption(
            f"Best orientation: drawing rotated {submission['rotation_degrees']:.0f}° "
            "counterclockwise for comparison."
        )

    rounding = settings["difficulty"]["rounding"]
    if rounding:
        st.caption(f"Both outlines use coastline rounding strength {rounding:g}.")
    st.caption(
        "Area overlap is reduced by border mismatches and distant contour sections. "
        "Both shapes are centered and scaled uniformly; proportions count. "
        "The overlay uses the same rotation and rounding as the score."
    )
