from copy import deepcopy

import streamlit as st
from streamlit_drawable_canvas import st_canvas

from src.utils.constants import DEFAULT_COUNTRY_CODE, DEFAULT_GAP_TOLERANCE_PIXELS
from src.utils.countries import get_all_country_names
from src.utils.geography import filter_landmasses, load_country_geometries
from src.utils.scoring import (
    country_to_mask,
    create_overlay,
    drawing_to_mask,
    score_with_difficulty,
)

st.set_page_config(page_title="BorderLines", page_icon="🌍")
st.title("BorderLines 🌍")

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
    value=0,
    help=(
        "Keep landmasses at least this percentage of the largest landmass's geographic area. "
        "0 includes everything. 20 keeps landmasses at least one fifth as large as the largest."
    ),
)

st.sidebar.subheader("Difficulty")
allow_rotation = st.sidebar.checkbox(
    "Allow rotations",
    value=False,
    help="Try different drawing orientations and keep the highest shape-match score.",
)
coastline_rounding = st.sidebar.slider(
    "Coastline rounding",
    min_value=0.0,
    max_value=5.0,
    value=0.0,
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
    index=list(country_names).index(DEFAULT_COUNTRY_CODE),
    format_func=country_names.get,
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
    key=f"canvas_{country_code_str}",
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
