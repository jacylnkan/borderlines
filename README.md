# borderlines
Do you actually know what Italy looks like?

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m streamlit run src/app.py
```

Open the local URL printed by Streamlit (usually http://localhost:8501).

## Drawing and scoring

### Game modes

The page appears when you first open a session:

- **1 Player:** Selecting this option opens the drawing canvas immediately.
- **2 Players:** Enter two different player names, then start the game. Player 1
  sees a turn announcement before opening the canvas and choosing the country and
  difficulty. After a valid submission, pass the device to player 2 at the handoff
  screen. Player 2 gets a fresh canvas with the same country and scoring settings.
  Neither player's score or reference overlay is revealed until both have submitted.
  The results screen shows both scores and overlays and announces the winner or tie.

This is local, pass-the-device play in one browser session. **Play another round**
keeps the names and starts a fresh round; **New game** reopens the mode picker.

- Choose from the nearly 200 countries and territories supported by the map dataset,
  sorted by display name.
- Draw each landmass in as many strokes as you like, keeping north at the top.
  Lift the pen and continue near a previous endpoint; strokes can be drawn in either
  direction or out of sequence. The nearest endpoints within **40 canvas pixels**
  are joined by default. Independently closed islands stay separate. Larger tolerances
  can also connect nearby open islands; check the overlay to see the resulting shape.
  Small gaps in the assembled outline close automatically with a straight segment.
  Final closure allows the larger of the chosen tolerance and 20% of the outline's
  diagonal, provided the gap is no more than 25% of the traced length. This keeps
  short unfinished arcs available to join rather than turning them into tiny islands.
  Crossings and retraced sections are repaired into filled regions rather than
  rejected. Clearly unfinished outlines, empty drawings, and strokes enclosing
  no area still show a reminder to finish drawing.
  Adjust the stroke width in the sidebar, or use the toolbar to undo/clear.
- Click **Submit drawing** to see a shape-match score out of 100 and an overlay:
  blue is the real country, orange is your drawing, and purple is their overlap.
  The overlay shows the repaired outline used for scoring. Cleanup preserves border
  detail rather than smoothing it or replacing the drawing with its convex hull.
- Both shapes are centered and uniformly scaled to 256 × 256 masks. Scoring combines
  filled-area overlap with border matching and contour distance. Drawing size,
  position, color, and line thickness do not count; aspect ratio counts, and orientation
  counts when rotation matching is disabled.
- The country is rendered with a local Lambert azimuthal equal-area projection. By
  default, all landmasses are included. Change **Minimum landmass size (%)** in the
  sidebar to filter out smaller islands and overseas territories. The cutoff percentage
  is relative to the largest landmass, which is always retained, even for very small
  countries.
- The latest successful submission stays in the current Streamlit session. Editing
  requires resubmitting to update the displayed result. Submissions are not permanent.

Country landmass areas are measured geodesically on WGS84, so latitude does not
distort the cutoff. Small disconnected landmasses in the drawing are filtered by
their canvas area using the same relative cutoff. Filtering happens before centering,
projection, and scaling; distant tiny islands cannot stretch the target across the
canvas. The score and overlay use the same filtered shapes. Changing the cutoff
requires a new submission.

With the supplied dataset, setting the minimum landmass size to 5% will keep Great Britain
and Northern Ireland, Japan's four largest islands, and New Zealand's two main islands.
This is an **area filter**, not a mainland or distance filter: large overseas areas such as French
Guiana still qualify, and Greenland remains part of Denmark's sovereignty geometry.

### Difficulty settings

The sidebar's **Difficulty** section offers:

- **Allow rotations:** Off by default. When enabled, compare orientations around the
  full circle every 15 degrees, then refine the three best neighborhoods at one-degree
  intervals. Keep the highest score, including the unrotated baseline. This approximate
  search rotates the entire drawing, keeps island positions relative to each other,
  avoids clipping, and normalizes size again after rotation. It does not mirror shapes.
  The result displays the counterclockwise rotation used in the overlay.
- **Coastline rounding:** 0–5 in half-pixel steps, defaulting to 0 for full detail.
  Gaussian smoothing softens both filled masks before border comparison, making
  fine coastline jaggedness less important. Larger values can remove tiny islands,
  narrow features, and small bays. Smoothing is not guaranteed to increase every drawing's
  score; it changes the detail level being compared.

The score components and overlay always use the same processed shapes. Changing a
difficulty setting requires resubmission; the original drawing on the canvas is kept.
For multiplayer rounds, use the same difficulty settings for all players.

### How the score works

The result shows three components, each on a 0–100 scale:

1. **Area overlap:** intersection over union (IoU) of the filled shapes.
2. **Border match:** boundary F1. Precision measures how much of your border is near
   the real border; recall measures how much of the real border you captured.
   Their harmonic mean penalizes both extra edges and missing features. Edges within
   2% of the image diagonal (about 7 pixels at 256 × 256) count as nearby.
3. **Contour similarity:** an exponential distance penalty. Measures how far apart the two
   outlines are, considering both typical differences and larger mistakes. Misplaced
   peninsulas or islands lower the score, while a single stray pixel has little effect.

Using component values between 0 and 1, the final score is:

```text
100 * area_overlap * border_match**0.30 * contour_similarity**0.15
```

## Map data

The app reads `data/ne_50m_admin_0_sovereignty.shp` directly with GeoPandas.
Keep the `.shp`, `.shx`, `.dbf`, `.prj`, and `.cpg` files together.
The loader converts the coordinate system to WGS84 in memory and caches the shapes.

This Natural Earth sovereignty dataset maps to 197 `pycountry` country codes.
The dropdown only includes countries with a mapped outline, including entries that
need fallback codes such as the US, UK, and France. The sovereignty shapes group
islands and overseas territories. Dataset borders and groupings define the game's
reference shapes.
