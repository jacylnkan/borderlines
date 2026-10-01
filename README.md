# borderlines
Do you actually know what Italy looks like?

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run src/app.py
```

Open the local URL printed by Streamlit (usually http://localhost:8501).

## First prototype

- Choose from the 249 countries and territories in `pycountry`, sorted by name.
- Draw the selected country's borders on the canvas. Adjust the stroke width and
  color in the sidebar, or use the canvas toolbar to undo or clear your drawing.
- Click **Submit drawing** to save the selected country and a snapshot of the
  drawing in the current Streamlit session. Empty drawings show a reminder to draw
  first. Each successful submission replaces the previous one; submissions are
  not saved permanently.

Scoring, real-border overlays, and multiplayer competition are planned for later
iterations.
