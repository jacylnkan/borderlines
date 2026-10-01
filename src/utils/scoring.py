"""Compare filled outlines independently of canvas position and uniform scale."""

import numpy as np
from PIL import Image, ImageDraw
from pyproj import CRS, Transformer
from scipy.ndimage import binary_erosion, distance_transform_edt
from shapely.geometry import Polygon
from shapely.ops import transform, unary_union


def geometry_to_mask(geometry, size=256, padding=12):
    """Rasterize a Cartesian outline into a centered, aspect-preserving Boolean mask.

    Fit the geometry's bounding box inside a square image with a uniform scale.
    Flip the vertical axis because Cartesian y increases upwards while image rows
    increase downwards. Fill each polygon independently, subtract its holes, then
    union the rasterized components so a hole cannot erase a different polygon.

    Args:
        geometry (shapely.geometry.Polygon | shapely.geometry.MultiPolygon): Valid,
            nonempty geometry with positive area and finite Cartesian coordinates.
            Geographic longitude/latitude should be projected before calling this.
        size (int): Image width and height in pixels; defaults to 256.
        padding (int): Nonnegative margin in pixels, defaulting to 12. The image
            size must be greater than twice this value.

    Returns:
        numpy.ndarray: Boolean array of shape ``(size, size)`` with filled land
        pixels set to True. Relative component positions and aspect ratio are kept;
        original translation and uniform scale are removed.

    Raises:
        ValueError: The geometry is empty, has nonpositive area or nonfinite bounds,
            or the requested padding leaves no valid image space.
    """
    if geometry.is_empty or geometry.area <= 0:
        raise ValueError("Draw an outline enclosing an area before submitting.")
    if size <= 2 * padding or padding < 0:
        raise ValueError("The mask must have space inside its padding.")
    min_x, min_y, max_x, max_y = geometry.bounds
    if not np.isfinite(geometry.bounds).all():
        raise ValueError("The outline contains invalid coordinates.")
    width, height = max_x - min_x, max_y - min_y
    scale = (size - 1 - 2 * padding) / max(width, height)
    offset_x = (size - 1 - width * scale) / 2
    offset_y = (size - 1 - height * scale) / 2

    def to_pixels(ring):
        """Convert a polygon ring with the enclosing mask's shared scale and offsets.

        Args:
            ring (shapely.geometry.LinearRing): Two-dimensional Cartesian ring.

        Returns:
            list[tuple[float, float]]: Image-space (column, row) coordinates, with
            the vertical axis reversed. Values remain floating-point for Pillow.
        """
        return [
            (offset_x + (x - min_x) * scale, offset_y + (max_y - y) * scale)
            for x, y in ring.coords
        ]

    polygons = [geometry] if geometry.geom_type == "Polygon" else geometry.geoms
    mask = np.zeros((size, size), dtype=bool)
    for polygon in polygons:
        image = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(image)
        draw.polygon(to_pixels(polygon.exterior), fill=255)
        for hole in polygon.interiors:
            draw.polygon(to_pixels(hole), fill=0)
        mask |= np.asarray(image) > 0
    return mask


def country_to_mask(geometry, size=256, padding=12):
    """Project a WGS84 country outline and normalize it into a scoring mask.

    Use a Lambert azimuthal equal-area projection centered on an interior point of
    the component with the greatest Shapely area in the input coordinate system.
    This anchor selection uses square degrees, unlike the geodesic landmass filter.
    Projection receives coordinates in longitude/latitude order. Call
    ``filter_landmasses`` first if smaller components should be excluded.

    Args:
        geometry (shapely.geometry.Polygon | shapely.geometry.MultiPolygon): Valid,
            nonempty country geometry in WGS84 longitude/latitude coordinates.
        size (int): Width and height of the output mask, defaulting to 256 pixels.
        padding (int): Margin passed to ``geometry_to_mask``, defaulting to 12 pixels.

    Returns:
        numpy.ndarray: Centered Boolean land mask of shape ``(size, size)`` in the
        local projection, with uniformly scaled dimensions and preserved holes.

    Raises:
        ValueError: Rasterization rejects the projected geometry or mask dimensions.
        pyproj.exceptions.ProjError: The projection cannot be constructed or executed.
    """
    parts = [geometry] if geometry.geom_type == "Polygon" else geometry.geoms
    # Anchor on the largest landmass, rather than an average of remote territories.
    center = max(parts, key=lambda part: part.area).representative_point()
    local_crs = CRS.from_proj4(
        f"+proj=laea +lat_0={center.y} +lon_0={center.x} +datum=WGS84 +units=m"
    )
    transformer = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)
    projected = transform(transformer.transform, geometry)
    return geometry_to_mask(projected, size, padding)


def _sample_path(commands):
    """Approximate one Fabric freehand subpath with an ordered array of points.

    Accept an initial absolute M command, absolute L/Q/C commands, and Z or z for
    explicit closure. Quadratic and cubic Bezier segments contribute 16 samples each,
    excluding the already-recorded start point. Multiple subpaths and other relative
    commands are unsupported. Closure is recorded but no closing point is appended.

    Args:
        commands (Sequence[Sequence]): Fabric path commands, each containing a command
            letter followed by numeric coordinates in the path's local coordinate space.

    Returns:
        tuple[numpy.ndarray, bool]: An ``(N, 2)`` floating-point array of sampled
        coordinates and whether an explicit close command was encountered.

    Raises:
        ValueError: Coordinates are nonfinite or nonnumeric, command types/order or
            coordinate counts are unsupported, or fewer than three points result.
    """
    points = []
    closed = False
    for command in commands:
        kind = command[0]
        values = np.asarray(command[1:], dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("The drawing contains invalid coordinates.")
        if kind == "M" and len(values) == 2 and not points:
            points.append(values)
        elif kind == "L" and len(values) == 2 and points:
            points.append(values)
        elif kind in ("Q", "C") and points:
            expected = 4 if kind == "Q" else 6
            if len(values) != expected:
                raise ValueError("The drawing contains an invalid curve.")
            start = points[-1]
            controls = values.reshape(-1, 2)
            for t in np.linspace(0, 1, 17)[1:]:
                if kind == "Q":
                    point = (1 - t) ** 2 * start
                    point += 2 * (1 - t) * t * controls[0] + t**2 * controls[1]
                else:
                    point = (1 - t) ** 3 * start
                    point += 3 * (1 - t) ** 2 * t * controls[0]
                    point += 3 * (1 - t) * t**2 * controls[1] + t**3 * controls[2]
                points.append(point)
        elif kind in ("Z", "z") and points:
            closed = True
        else:
            raise ValueError("Use one continuous freehand stroke for each landmass.")
    if len(points) < 3:
        raise ValueError("Draw an outline enclosing an area before submitting.")
    return np.asarray(points), closed


def _canvas_points(obj):
    """Resolve a Fabric path's object transform into Cartesian outline coordinates.

    Sample the local path, apply path offset, scale, flips, origin, rotation, and
    translation, then invert y to convert canvas coordinates to Cartesian coordinates.
    Use stroke width only to recover Fabric's positioning; do not inflate the filled
    outline by the painted stroke. When pathOffset is absent, estimate it from the
    sampled bounds. A nonexplicitly closed path must end within 10% of its sampled
    bounding-box diagonal from its starting point; Polygon closes accepted gaps later.

    Args:
        obj (dict): Serialized Fabric Path object with a ``path`` command list and
            optional standard transform and bounding-box fields. Omitted transform
            values use identity/default placement; omitted dimensions use sampled bounds.

    Returns:
        numpy.ndarray: Finite floating-point array of shape ``(N, 2)`` in Cartesian
        canvas units. Relative placement between separate paths is preserved.

    Raises:
        ValueError: Path sampling fails, skew is nonzero, transformed coordinates are
            nonfinite, or an open path's endpoint gap exceeds the closure tolerance.
    """
    points, closed = _sample_path(obj.get("path", []))
    bounds_min, bounds_max = points.min(axis=0), points.max(axis=0)
    offset = obj.get("pathOffset")
    offset = np.array([offset["x"], offset["y"]]) if offset else (bounds_min + bounds_max) / 2
    scale = np.array([obj.get("scaleX", 1), obj.get("scaleY", 1)], dtype=float)
    dimensions = np.array(
        [
            obj.get("width", bounds_max[0] - bounds_min[0]),
            obj.get("height", bounds_max[1] - bounds_min[1]),
        ]
    )
    if obj.get("skewX", 0) or obj.get("skewY", 0):
        raise ValueError("Skewed shapes are not supported. Please redraw the outline.")
    angle = np.deg2rad(obj.get("angle", 0))
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    origins = {"left": -0.5, "top": -0.5, "center": 0, "right": 0.5, "bottom": 0.5}
    origin = np.array([origins[obj.get("originX", "left")], origins[obj.get("originY", "top")]])
    # Fabric's left/top include the stroke, but scoring uses the path centerline.
    center = np.array([obj.get("left", 0), obj.get("top", 0)], dtype=float)
    center -= rotation @ (origin * (dimensions + obj.get("strokeWidth", 1)) * scale)
    flips = np.array([-1 if obj.get("flipX") else 1, -1 if obj.get("flipY") else 1])
    points = ((points - offset) * scale * flips) @ rotation.T + center
    if not np.isfinite(points).all():
        raise ValueError("The drawing contains invalid coordinates.")
    span = np.linalg.norm(np.ptp(points, axis=0))
    if not closed and np.linalg.norm(points[-1] - points[0]) > 0.1 * span:
        raise ValueError("Close each outline: finish your stroke near where it started.")
    # Canvas y increases downwards; geometry y increases upwards.
    points[:, 1] *= -1
    return points


def drawing_to_mask(drawing, size=256, padding=12, min_area_ratio=0.0):
    """Validate, fill, filter, and normalize a canvas drawing for shape comparison.

    Accept Fabric's ``path`` and ``Path`` object types. Each stroke must independently
    enclose a positive, non-self-intersecting area; small endpoint gaps accepted by
    ``_canvas_points`` are closed by Polygon. Union strokes before filtering, so
    overlapping strokes form one landmass. Nested strokes add land rather than holes.
    Remove small disconnected components before the remaining shape is normalized.

    Args:
        drawing (dict | None): Canvas JSON containing an ``objects`` list of serialized
            freehand paths. None or an empty object list is treated as an empty drawing.
        size (int): Square mask width and height in pixels, defaulting to 256.
        padding (int): Nonnegative raster margin in pixels, defaulting to 12.
        min_area_ratio (float): Inclusive component-area threshold relative to the
            largest unioned component, in [0, 1]. Defaults to 0 (retain all). Areas
            here use Cartesian canvas units, not geographic coordinates.

    Returns:
        numpy.ndarray: Boolean ``(size, size)`` mask of retained filled landmasses,
        centered and uniformly scaled independently of stroke color and thickness.

    Raises:
        ValueError: The cutoff is invalid, the drawing is empty or contains unsupported
            objects, a stroke is open/degenerate/self-crossing, or path transformation
            or mask rasterization fails validation.
    """
    if not 0 <= min_area_ratio <= 1:
        raise ValueError("The landmass cutoff must be between 0 and 1.")
    polygons = []
    for obj in (drawing or {}).get("objects", []):
        # Fabric 7 serializes "Path"; older canvas versions used "path".
        if str(obj.get("type", "")).lower() != "path":
            raise ValueError("Use freehand outlines to draw the country.")
        polygon = Polygon(_canvas_points(obj))
        if polygon.area <= 0:
            raise ValueError("Draw an outline enclosing an area before submitting.")
        if not polygon.is_valid:
            raise ValueError("Your outline crosses itself. Undo that stroke and try again.")
        polygons.append(polygon)
    if not polygons:
        raise ValueError("Draw the country's borders before submitting.")
    geometry = unary_union(polygons)
    if min_area_ratio and geometry.geom_type == "MultiPolygon":
        cutoff = max(part.area for part in geometry.geoms) * min_area_ratio
        geometry = unary_union([part for part in geometry.geoms if part.area >= cutoff])
    return geometry_to_mask(geometry, size, padding)


def calculate_accuracy(drawing_mask, country_mask):
    """Return the overall border-aware score without its component breakdown.

    Delegate validation and scoring to ``calculate_score_breakdown``. Masks must
    already share a coordinate frame; this function performs no alignment or resizing.

    Args:
        drawing_mask (array-like): Finite, nonempty two-dimensional numeric or Boolean
            array. Nonzero pixels represent the player's filled land area.
        country_mask (array-like): Reference land mask with the same shape and encoding.

    Returns:
        float: Score in [0, 100], never greater than the area-overlap percentage.
        Identical nonempty land masks score 100; either mask lacking land scores zero.

    Raises:
        ValueError: Shapes differ, masks are not nonempty two-dimensional arrays, or
            contain nonfinite values, as checked by ``calculate_score_breakdown``.
    """
    return calculate_score_breakdown(drawing_mask, country_mask)["score"]


def calculate_score_breakdown(drawing_mask, country_mask):
    """Combine area overlap, bidirectional border F1, and contour-distance quality.

    Extract border pixels with four-connected binary erosion, treating pixels outside
    the image as background. Include island edges and hole boundaries. Measure nearest
    Euclidean border distances in both directions with distance transforms.

    Border precision/recall count distances within 1% of the image diagonal; their
    harmonic mean is the border F1. Let mean be the average of the two directional
    distance means, and p95 the larger directional 95th percentile. Contour quality is
    ``exp(-(0.5 * mean + 0.5 * p95) / (0.035 * diagonal))``. Using fractions in [0, 1],
    the final score is ``100 * IoU * border_F1**0.65 * contour_quality**0.35``.
    These weights are game heuristics, not calibrated geographic accuracy percentages.

    Args:
        drawing_mask (array-like): Finite, nonempty two-dimensional numeric or Boolean
            mask already aligned and normalized for comparison. Nonzero values are land.
        country_mask (array-like): Reference mask with the same shape and interpretation.

    Returns:
        dict[str, float]: Values on a 0–100 scale under ``score`` (combined result),
        ``area_overlap`` (IoU), ``border_match`` (boundary F1), and ``contour_similarity``
        (distance quality). All values are zero if either mask contains no land.
        The combined score is symmetric and never exceeds the area-overlap score.

    Raises:
        ValueError: Mask shapes differ, either mask is not two-dimensional or has no
            elements, or either contains NaN or infinite values.
    """
    drawing_mask = np.asarray(drawing_mask)
    country_mask = np.asarray(country_mask)
    if drawing_mask.shape != country_mask.shape:
        raise ValueError("Both masks must have the same dimensions.")
    if drawing_mask.ndim != 2 or not drawing_mask.size:
        raise ValueError("Scoring requires nonempty two-dimensional masks.")
    if not np.isfinite(drawing_mask).all() or not np.isfinite(country_mask).all():
        raise ValueError("Masks must contain finite values.")
    drawing_mask = drawing_mask.astype(bool)
    country_mask = country_mask.astype(bool)
    if not drawing_mask.any() or not country_mask.any():
        return dict(score=0.0, area_overlap=0.0, border_match=0.0, contour_similarity=0.0)

    intersection = np.logical_and(drawing_mask, country_mask).sum()
    union = np.logical_or(drawing_mask, country_mask).sum()
    overlap = float(intersection / union)

    # Include island edges and interior holes, including boundaries at image edges.
    drawing_border = drawing_mask & ~binary_erosion(drawing_mask, border_value=0)
    country_border = country_mask & ~binary_erosion(country_mask, border_value=0)
    to_country = distance_transform_edt(~country_border)[drawing_border]
    to_drawing = distance_transform_edt(~drawing_border)[country_border]
    diagonal = float(np.hypot(*country_mask.shape))
    tolerance = 0.01 * diagonal
    precision = float(np.mean(to_country <= tolerance))
    recall = float(np.mean(to_drawing <= tolerance))
    border_match = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    mean_distance = (to_country.mean() + to_drawing.mean()) / 2
    tail_distance = max(np.percentile(to_country, 95), np.percentile(to_drawing, 95))
    contour_similarity = float(
        np.exp(-(0.5 * mean_distance + 0.5 * tail_distance) / (0.035 * diagonal))
    )
    score = 100 * overlap * border_match**0.65 * contour_similarity**0.35
    return {
        "score": float(np.clip(score, 0, 100)),
        "area_overlap": 100 * overlap,
        "border_match": 100 * border_match,
        "contour_similarity": 100 * contour_similarity,
    }


def create_overlay(drawing_mask, country_mask):
    """Render a color-coded comparison of the exact masks used for scoring.

    Args:
        drawing_mask (numpy.ndarray): Two-dimensional Boolean player mask.
        country_mask (numpy.ndarray): Boolean reference mask of the same shape.
            Both masks must already be aligned; no resizing or normalization occurs.

    Returns:
        numpy.ndarray: RGB image of shape ``(height, width, 3)`` and dtype uint8.
        Reference-only pixels are blue (59, 130, 246), drawing-only pixels are orange
        (249, 150, 55), overlap is purple (147, 80, 190), and background is (245, 245, 245).
        Neither input mask is modified. The result is suitable for ``st.image``.
    """
    overlay = np.full((*country_mask.shape, 3), 245, dtype=np.uint8)
    overlay[country_mask] = (59, 130, 246)
    overlay[drawing_mask] = (249, 150, 55)
    overlay[np.logical_and(drawing_mask, country_mask)] = (147, 80, 190)
    return overlay
