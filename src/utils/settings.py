from uuid import uuid4

import streamlit as st


def start_game(players):
    """Initialize one local game and clear results from a previous game.

    Args:
        players (list[str]): One solo label or two validated player names in turn order.

    Returns:
        None: Stores game state in the current Streamlit session. A unique ID isolates
        canvas contents from other games. Multiplayer starts on a handoff screen.
    """
    st.session_state["game"] = {
        "id": uuid4().hex,
        "players": players,
        "turn": 0,
        "stage": "turn" if len(players) == 2 else "canvas",
        "submissions": [],
        "round_settings": {},
    }
    st.session_state.pop("submission", None)


@st.dialog(title="Welcome to BorderLines!", width="large", dismissible=False)
def configure_game():
    """Show the initial mode picker and collect names for local two-player play.

    Selecting Single player starts immediately. Selecting 2 players reveals a form;
    both nonempty, distinct names are required before the first handoff screen.
    A successful selection reruns the full app with initialized session game state.
    """
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
