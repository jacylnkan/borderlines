from copy import deepcopy

import streamlit as st
from streamlit_drawable_canvas import st_canvas

from src.utils.constants import DEFAULT_COUNTRY_CODE
from src.utils.utils import get_all_country_names

st.set_page_config(page_title="BorderLines", page_icon="🌍")
st.title("BorderLines 🌍")

stroke_width = st.sidebar.slider("Stroke width: ", 1, 25, 3)
stroke_color = st.sidebar.color_picker("Stroke color: ")

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

canvas_result = st_canvas(
    stroke_width=stroke_width,
    stroke_color=stroke_color,
    background_color="#eee",
    height=600,
    width=700,
    update_streamlit=True,
    drawing_mode="freedraw",
    return_image_data=True,
    key=f"canvas_{country_code_str}",
)

if st.button("Submit drawing", type="primary"):
    drawing = canvas_result.json_data
    if not drawing or not drawing.get("objects"):
        st.error("Draw the country's borders before submitting.")
    else:
        st.session_state["submission"] = {
            "country_code": country_code,
            "country_name": country_names[country_code_str],
            "drawing": deepcopy(drawing),
            "image": (
                canvas_result.image_data.copy()
                if canvas_result.image_data is not None
                else None
            ),
        }
        st.success(f"Your drawing of {selected_country_name_no_flag} was submitted!")
