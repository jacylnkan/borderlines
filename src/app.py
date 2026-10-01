from copy import deepcopy

import streamlit as st
from streamlit_drawable_canvas import st_canvas

from utils.constants import DEFAULT_COUNTRY_CODE
from utils.countries import get_all_country_names
from utils.geography import filter_landmasses, load_country_geometries
from utils.scoring import (
    calculate_score_breakdown,
    country_to_mask,
    create_overlay,
    drawing_to_mask,
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
    value=5,
    help=(
        "Keep landmasses at least this percentage of the largest landmass's geographic area. "
        "0 includes everything. 20 keeps landmasses at least one fifth as large as the largest."
    ),
)

gap_tolerance = st.sidebar.slider(
    "Gap tolerance (canvas pixels)",
    min_value=5,
    max_value=100,
    value=40,
    step=5,
    help=(
        "Increase this to connect strokes across larger gaps and help close outlines. "
        "The nearest endpoints are joined with straight lines."
    ),
)

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
    "Small gaps and accidental crossings are fixed automatically. "
    "Keep north at the top; position and overall size do not affect the score."
)
st.caption(
    f"Strokes up to {gap_tolerance} canvas pixels apart can join. "
    "Increase Gap tolerance in the sidebar if sections are still unfinished."
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
                drawing, min_area_ratio=landmass_cutoff / 100, gap_tolerance=gap_tolerance
            )
            target_geometry = filter_landmasses(geometry, landmass_cutoff / 100)
            country_mask = country_to_mask(target_geometry)
            score_breakdown = calculate_score_breakdown(drawing_mask, country_mask)
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
                "gap_tolerance": gap_tolerance,
                "overlay": create_overlay(drawing_mask, country_mask),
            }
            st.success(f"Your drawing of {selected_country_name_no_flag} was submitted!")

submission = st.session_state.get("submission")
if submission and submission["country_code"] == country_code_str:
    if submission.get("gap_tolerance") != gap_tolerance:
        st.info("Submit your drawing again to use the current gap tolerance.")
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
        help="Checks both outlines for matching edges within about 3.6 pixels.",
    )
    contour.metric(
        "Contour similarity",
        f"{breakdown['contour_similarity']:.1f}/100",
        help="Penalizes average border distance and large errors along either outline.",
    )
    st.image(submission["overlay"], width=400)
    st.caption("Blue: actual country · Orange: your drawing · Purple: overlap")
    st.caption(
        "Area overlap is reduced by border mismatches and distant contour sections. "
        "Both shapes are centered and scaled uniformly; proportions and orientation count."
    )
