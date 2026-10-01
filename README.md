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

- Choose from the nearly 200 countries and territories supported by the map dataset,
  sorted by display name.
- Draw one continuous closed outline per landmass, keeping north at the top.
  Small endpoint gaps (up to 10% of the stroke's bounding-box diagonal) close
  automatically. Open strokes, crossing outlines, and empty drawings are rejected.
  Adjust the stroke width and color in the sidebar, or use the toolbar to undo/clear.
- Click **Submit drawing** to see a shape-match score out of 100 and an overlay:
  blue is the real country, orange is your drawing, and purple is their overlap.
- Both shapes are centered and uniformly scaled to 256 × 256 masks. Scoring combines
  filled-area overlap with border matching and contour distance. Drawing size,
  position, color, and line thickness do not count; aspect ratio and orientation do.
- The country is rendered with a local Lambert azimuthal equal-area projection.
  By default, only landmasses with at least **5% of the largest landmass's area**
  are included. Change **Minimum landmass size (%)** in the sidebar; 0 restores all
  land areas. The largest landmass is always retained, even for very small countries.
  Separate drawn strokes are filled and combined; drawing interior holes is not
  supported yet.
- The latest successful submission stays in the current Streamlit session. Editing
  requires resubmitting to update the displayed result. Submissions are not permanent.

Country landmass areas are measured geodesically on WGS84, so latitude does not
distort the cutoff. Small disconnected landmasses in the drawing are filtered by
their canvas area using the same relative cutoff. Filtering happens before centering,
projection, and scaling; distant tiny islands cannot stretch the target across the
canvas. The score and overlay use the same filtered shapes. Changing the cutoff
requires a new submission.

With the supplied dataset, the 5% default keeps Great Britain and Northern Ireland,
Japan's four largest islands, and New Zealand's two main islands. This is an **area
filter**, not a mainland or distance filter: large overseas areas such as French
Guiana still qualify, and Greenland remains part of Denmark's sovereignty geometry.

### How the score works

The result shows three components, each on a 0–100 scale:

1. **Area overlap:** intersection over union (IoU) of the filled shapes.
2. **Border match:** boundary F1. Precision measures how much of your border is near
   the real border; recall measures how much of the real border you captured.
   Their harmonic mean penalizes both extra edges and missing features. Edges within
   1% of the image diagonal (about 3.6 pixels at 256 × 256) count as nearby.
3. **Contour similarity:** an exponential distance penalty combining the average
   border error in both directions with the larger directional 95th-percentile error.
   This penalizes badly misplaced peninsulas, islands, and other contour sections
   without letting a single stray pixel dominate the result.

Using component values between 0 and 1, the final score is:

```text
100 * area_overlap * border_match**0.65 * contour_similarity**0.35
```

The contour-distance component is `exp(-(0.5 * mean + 0.5 * p95) / (0.035 * diagonal))`.
The final score never exceeds raw area overlap, so covering roughly the right area
with a blob is no longer sufficient for a high score. An identical mask scores 100;
small hand-drawing errors receive some tolerance. Rotation and reflection are not
aligned away. These weights are game heuristics rather than calibrated accuracy
percentages; naturally compact countries can still resemble simple rounded shapes.

## Map data

The app reads `data/ne_50m_admin_0_sovereignty.shp` directly with GeoPandas; no GeoJSON
conversion is needed. Keep the `.shp`, `.shx`, `.dbf`, `.prj`, and `.cpg` files together.
The loader converts the coordinate system to WGS84 in memory and caches the shapes.

This Natural Earth sovereignty dataset maps to 197 `pycountry` country codes.
The dropdown only includes countries with a mapped outline, including entries that
need fallback codes such as the US, UK, and France. The sovereignty shapes group
islands and overseas territories. The landmass cutoff removes small components,
but large distant territories can still make targets widely dispersed. Dataset
borders and groupings define the game's reference shapes.
