"""Streamlit entry point: choose a screen, collect a drawing, and submit it."""

import streamlit as st
from streamlit_drawable_canvas import st_canvas

from src.data.countries import get_all_country_names, load_country_geometries
from src.game import get_game, save_submission, score_submission
from src.utils.constants import (
    CANVAS_BACKGROUND_COLOUR,
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    STYLES_PATH,
)
from src.visualizations.ui import (
    show_drawing_instructions,
    show_game_menu,
    show_round_results,
    show_sidebar,
    show_solo_result,
    show_turn_screen,
    show_welcome,
)


def main() -> None:
    """Route welcome, handoff, drawing, and results screens for the active session."""
    st.set_page_config(page_title="BorderLines", page_icon="🌍")
    st.html(f"<style>{STYLES_PATH.read_text(encoding='utf-8')}</style>")

    game = get_game()

    if game is None:
        show_welcome()
        return

    show_game_menu()

    if game["stage"] != "turn" and game["stage"] != "results":
        st.title("BorderLines 🌍")
    if game["stage"] == "turn":
        show_turn_screen(game)
        return
    if game["stage"] == "results":
        show_round_results(game)
        return

    try:
        geometries = load_country_geometries()
        country_names = get_all_country_names()
    except (OSError, ValueError) as error:
        st.error(f"Could not load the country Shapefile: {error}")
        return

    multiplayer = len(game["players"]) > 1
    if multiplayer:
        st.subheader(f"{game['players'][game['turn']]}'s turn")

    canvas_settings, round_settings = show_sidebar(game, country_names)

    country_code = round_settings["country_code"]
    country_name = country_names[country_code]
    geometry = geometries.get(country_code)
    name_without_flag = country_name.rsplit(" ", 1)[0]

    show_drawing_instructions(name_without_flag, round_settings)

    canvas = st_canvas(
        **canvas_settings,
        background_color=CANVAS_BACKGROUND_COLOUR,
        height=CANVAS_HEIGHT,
        width=CANVAS_WIDTH,
        update_streamlit=True,
        drawing_mode="freedraw",
        return_image_data=False,
        key=f"canvas_{game['id']}_{game['turn']}_{country_code}",
    )

    if st.button("Submit drawing", type="primary", disabled=geometry is None):
        drawing = canvas.json_data

        if not drawing or not drawing.get("objects"):
            st.error("Draw the country's borders before submitting.")
        elif geometry is not None:
            try:
                with st.spinner("Comparing your drawing with the country outline…"):
                    submission = score_submission(
                        drawing, geometry, country_name, round_settings
                    )
            except ValueError as error:
                st.error(str(error))
            else:
                save_submission(game, submission, round_settings)
                if multiplayer:
                    st.rerun()
                st.success(f"Your drawing of {name_without_flag} was submitted!")

    show_solo_result(round_settings)


if __name__ == "__main__":
    main()
