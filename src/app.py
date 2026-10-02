from copy import deepcopy

import streamlit as st
from streamlit_drawable_canvas import st_canvas

from src.utils.constants import (
    DEFAULT_COUNTRY_CODE,
    DEFAULT_GAP_TOLERANCE_PIXELS,
    HTML_SETTINGS,
)
from src.utils.countries import get_all_country_names
from src.utils.geography import filter_landmasses, load_country_geometries
from src.utils.scoring import (
    country_to_mask,
    create_overlay,
    drawing_to_mask,
    score_with_difficulty,
)
from src.utils.settings import configure_game, start_game

st.set_page_config(page_title="BorderLines", page_icon="🌍")
st.html(HTML_SETTINGS)

current_stage = st.session_state.get("game", {}).get("stage")
if current_stage != "turn" and current_stage is not None:
    st.title("BorderLines 🌍")

if "game" not in st.session_state:
    configure_game()
    st.stop()

game = st.session_state["game"]
multiplayer = len(game["players"]) > 1

with st.sidebar.container(key="game_settings_heading"):
    st.subheader("Game Settings")

with st.sidebar.container(key="new_game_button"):
    if st.button("New game"):
        st.session_state.pop("game", None)
        st.session_state.pop("welcome_mode", None)
        st.rerun()

if game["stage"] == "turn":
    player = game["players"][game["turn"]]
    with st.container(key="turn_screen"):
        st.title("BorderLines 🌍")
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
    st.stop()

if game["stage"] == "results":
    first, second = game["submissions"]
    st.subheader("Round results")
    st.write(f"Country: {first['country_name']}")
    if abs(first["score"] - second["score"]) < 0.05:
        st.success("It's a tie!")
    else:
        winner = max(game["submissions"], key=lambda result: result["score"])
        st.success(f"{winner['player_name']} wins!")
    for column, result in zip(st.columns(2), game["submissions"]):
        with column:
            st.subheader(result["player_name"])
            st.metric("Shape match", f"{result['score']:.1f}/100")
            st.image(result["overlay"], width="stretch")
            st.caption("Blue: country · Orange: drawing · Purple: overlap")
    if st.button("Play another round", type="primary"):
        start_game(game["players"])
        st.rerun()
    st.stop()

locked = multiplayer and game["turn"] > 0
round_settings = game["round_settings"]
if multiplayer:
    st.subheader(f"{game['players'][game['turn']]}'s turn")

try:
    country_geometries = load_country_geometries()
except (OSError, ValueError) as error:
    st.error(f"Could not load the country Shapefile: {error}")
    st.stop()

stroke_width = st.sidebar.slider("Stroke width: ", 1, 25, 3)
stroke_color = st.sidebar.color_picker("Stroke color: ")
landmass_cutoff = st.sidebar.slider(
    "Minimum landmass size (%)",
    min_value=0,
    max_value=20,
    value=round_settings.get("landmass_cutoff", 0),
    disabled=locked,
    help=(
        "Keep landmasses at least this percentage of the largest landmass's geographic area. "
        "0 includes everything. 20 keeps landmasses at least one fifth as large as the largest."
    ),
)

st.sidebar.subheader("Difficulty")
allow_rotation = st.sidebar.checkbox(
    "Allow rotations",
    value=round_settings.get("difficulty", {}).get("allow_rotation", False),
    disabled=locked,
    help="Try different drawing orientations and keep the highest shape-match score.",
)
coastline_rounding = st.sidebar.slider(
    "Coastline rounding",
    min_value=0.0,
    max_value=5.0,
    value=round_settings.get("difficulty", {}).get("rounding", 0.0),
    disabled=locked,
    step=0.5,
    help=(
        "0 keeps full detail. Higher values soften jagged coastlines on both shapes. "
        "Strength is measured in pixels on the 256 × 256 scoring masks."
    ),
)
difficulty = {"allow_rotation": allow_rotation, "rounding": coastline_rounding}

country_names = get_all_country_names()
country_code = st.sidebar.selectbox(
    "Country",
    options=list(country_names),
    index=list(country_names).index(round_settings.get("country_code", DEFAULT_COUNTRY_CODE)),
    format_func=country_names.get,
    disabled=locked,
)

country_code_str = str(country_code)
selected_country_name_no_flag = " ".join(country_names[country_code_str].split(" ")[:-1])

st.subheader(f"Draw the borders of {selected_country_name_no_flag}!")
st.caption("Draw with your mouse. Use the canvas toolbar to undo or clear.")
st.caption(
    "Lift your pen whenever you like and continue near a previous stroke's endpoint. "
    "You can draw sections in either direction; nearby strokes join when you submit. "
    "Small gaps (up to 40 pixels) and accidental crossings are fixed automatically. "
    "Position and overall size do not affect the score."
)
st.caption(
    "Rotation matching is enabled; orientation will be adjusted for the best score."
    if allow_rotation
    else "Keep north at the top, or enable **Allow rotations** in the sidebar."
)
st.caption(
    f"The reference keeps landmasses at least {landmass_cutoff}% of the largest landmass's "
    "area. Smaller separate landmasses in your drawing are also ignored. Set the cutoff to 0 "
    "to include all land areas."
)
geometry = country_geometries.get(country_code_str)
if geometry is None:
    st.warning(
        "This dataset has no separate outline for this selection. Choose another country."
    )

canvas_result = st_canvas(
    stroke_width=stroke_width,
    stroke_color=stroke_color,
    background_color="#eee",
    height=600,
    width=700,
    update_streamlit=True,
    drawing_mode="freedraw",
    return_image_data=False,
    key=f"canvas_{game['id']}_{game['turn']}_{country_code_str}",
)

if st.button("Submit drawing", type="primary", disabled=geometry is None):
    drawing = canvas_result.json_data
    if not drawing or not drawing.get("objects"):
        st.error("Draw the country's borders before submitting.")
    else:
        try:
            drawing_mask = drawing_to_mask(
                drawing,
                min_area_ratio=landmass_cutoff / 100,
                gap_tolerance=DEFAULT_GAP_TOLERANCE_PIXELS,
            )
            target_geometry = filter_landmasses(geometry, landmass_cutoff / 100)
            country_mask = country_to_mask(target_geometry)
            with st.spinner("Comparing your drawing with the country outline…"):
                comparison = score_with_difficulty(drawing_mask, country_mask, **difficulty)
            score_breakdown = comparison["breakdown"]
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state["submission"] = {
                "country_code": country_code_str,
                "country_name": country_names[country_code_str],
                "drawing": deepcopy(drawing),
                "score": score_breakdown["score"],
                "score_breakdown": score_breakdown,
                "landmass_cutoff": landmass_cutoff,
                "difficulty": difficulty.copy(),
                "rotation_degrees": comparison["rotation_degrees"],
                "overlay": create_overlay(
                    comparison["drawing_mask"], comparison["country_mask"]
                ),
            }
            if multiplayer:
                submission = st.session_state["submission"]
                submission["player_name"] = game["players"][game["turn"]]
                game["submissions"].append(submission)
                game["round_settings"] = {
                    "country_code": country_code_str,
                    "difficulty": difficulty.copy(),
                    "landmass_cutoff": landmass_cutoff,
                }
                st.session_state.pop("submission", None)
                if game["turn"] == 0:
                    game["turn"] = 1
                    game["stage"] = "turn"
                else:
                    game["stage"] = "results"
                st.rerun()
            st.success(f"Your drawing of {selected_country_name_no_flag} was submitted!")

submission = st.session_state.get("submission")
if submission and submission["country_code"] == country_code_str:
    if submission.get("difficulty") != difficulty:
        st.info("Submit your drawing again to use the current difficulty settings.")
        st.stop()
    if submission.get("landmass_cutoff") != landmass_cutoff:
        st.info("Submit your drawing again to score it with the current landmass cutoff.")
        st.stop()
    if "score_breakdown" not in submission:
        st.info("Submit your drawing again to use the new border-aware scoring.")
        st.stop()
    st.subheader("Last submitted drawing")
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
    if allow_rotation:
        st.caption(
            f"Best orientation: drawing rotated {submission['rotation_degrees']:.0f}° "
            "counterclockwise for comparison."
        )
    if coastline_rounding:
        st.caption(f"Both outlines use coastline rounding strength {coastline_rounding:g}.")
    st.caption(
        "Area overlap is reduced by border mismatches and distant contour sections. "
        "Both shapes are centered and scaled uniformly; proportions count. "
        "The overlay uses the same rotation and rounding as the score."
    )
