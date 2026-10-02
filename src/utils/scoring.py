"""Compare filled outlines independently of canvas position and uniform scale."""

import numpy as np
from PIL import Image, ImageDraw
from pyproj import CRS, Transformer
from scipy.ndimage import binary_erosion, distance_transform_edt, gaussian_filter, rotate
from shapely import make_valid
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
            coordinate counts are unsupported, or fewer than two points result.
            Two-point fragments are allowed because other strokes can complete them.
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
            raise ValueError("This stroke has unsupported path commands. Please redraw it.")
    if len(points) < 2:
        raise ValueError("Draw a border segment before submitting.")
    return np.asarray(points), closed


def _canvas_points(obj):
    """Resolve a Fabric path's object transform into Cartesian outline coordinates.

    Sample the local path, apply path offset, scale, flips, origin, rotation, and
    translation, then invert y to convert canvas coordinates to Cartesian coordinates.
    Use stroke width only to recover Fabric's positioning; do not inflate the filled
    outline by the painted stroke. When pathOffset is absent, estimate it from the
    sampled bounds. Append the starting point for an explicit Z command. Otherwise
    leave endpoints open so ``_assemble_outlines`` can join separate pen strokes
    before deciding whether a complete landmass has been drawn.

    Args:
        obj (dict): Serialized Fabric Path object with a ``path`` command list and
            optional standard transform and bounding-box fields. Omitted transform
            values use identity/default placement; omitted dimensions use sampled bounds.

    Returns:
        numpy.ndarray: Finite floating-point array of shape ``(N, 2)`` in Cartesian
        canvas units. Relative placement between separate paths is preserved.

    Raises:
        ValueError: Path sampling fails, skew is nonzero, transformed coordinates are
            nonfinite.
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
    if closed and not np.array_equal(points[0], points[-1]):
        points = np.vstack((points, points[0]))
    # Canvas y increases downwards; geometry y increases upwards.
    points[:, 1] *= -1
    return points


def _assemble_outlines(paths, join_tolerance=40.0):
    """Join nearby stroke endpoints into complete landmasses before filling them.

    Repeatedly choose the shortest eligible endpoint connection across all paths.
    Reverse a stroke when needed, so drawing direction and input order do not impose
    a required tracing sequence. Self-closure competes with joins: closer continuation
    strokes are attached before a larger closing gap is bridged. Exact closures take
    priority over joins, preserving independently closed islands even if they touch.

    A chain may close when its endpoints are within 20% of its bounding-box diagonal
    (at least join_tolerance canvas units), the gap is at most 25% of the traced length,
    and its
    points are not collinear. The length check keeps short arcs available for joining
    instead of treating them as tiny closed islands. The convex hull is
    used only to check for noncollinearity; the actual stroke is passed unchanged to
    ``_repair_outline``. Ambiguous nearby endpoints are resolved by nearest distance;
    this is an endpoint heuristic, not recognition of the intended country's shape.

    Args:
        paths (Sequence[numpy.ndarray]): Finite Cartesian path arrays of shape (N, 2),
            each with at least two points and resolved Fabric object transforms.
        join_tolerance (float): Maximum gap between different strokes in canvas units,
            defaulting to 40. Also sets the minimum final-closure tolerance. Must be
            finite and nonnegative. Gaps are connected with straight segments.

    Returns:
        list: Repaired Polygon/MultiPolygon landmasses assembled from every path.
        Input arrays are not modified; stroke style has no effect on joining.

    Raises:
        ValueError: The tolerance is invalid, remaining fragments cannot form land, or
            repairing an assembled outline fails to produce a positive-area region.
    """
    if not np.isfinite(join_tolerance) or join_tolerance < 0:
        raise ValueError("Gap tolerance must be finite and nonnegative.")
    remaining = list(paths)
    polygons = []
    while remaining:
        best_distance = float("inf")
        connection = None
        # Inspect closures first so a complete island wins ties with adjacent strokes.
        for index, points in enumerate(remaining):
            gap = np.linalg.norm(points[-1] - points[0])
            tolerance = max(join_tolerance, 0.2 * np.linalg.norm(np.ptp(points, axis=0)))
            traced_length = np.linalg.norm(np.diff(points, axis=0), axis=1).sum()
            if (
                len(points) >= 3
                and gap <= tolerance
                and gap <= 0.25 * traced_length
                and gap < best_distance
                and Polygon(points).convex_hull.area > 0
            ):
                best_distance = gap
                connection = (index, index, 0, 0)
        for first in range(len(remaining)):
            for second in range(first + 1, len(remaining)):
                a = remaining[first][[0, -1]]
                b = remaining[second][[0, -1]]
                distances = np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2)
                a_end, b_end = np.unravel_index(np.argmin(distances), distances.shape)
                gap = distances[a_end, b_end]
                if gap <= join_tolerance and gap < best_distance:
                    best_distance = gap
                    connection = (first, second, a_end, b_end)
        if connection is None:
            raise ValueError(
                "Some border sections are unfinished. "
                "Continue drawing near the endpoints of each stroke before submitting."
            )
        first, second, a_end, b_end = connection
        if first == second:
            polygons.append(_repair_outline(remaining.pop(first)))
        else:
            a, b = remaining[first], remaining.pop(second)
            if a_end == 0:
                a = a[::-1]
            if b_end == 1:
                b = b[::-1]
            remaining[first] = np.vstack((a, b))
    return polygons


def _repair_outline(points):
    """Turn a nearly closed, possibly self-crossing stroke into valid filled land.

    Close the endpoint gap with a straight segment, then use Shapely's linework-based
    repair to split crossings into valid polygonal regions. Preserve those regions,
    including multiple lobes and holes, while discarding collapsed line or point
    fragments from retracing. Do not smooth borders or replace them with a convex hull.
    Valid polygons pass through unchanged.

    Args:
        points (numpy.ndarray): Finite Cartesian coordinates of shape ``(N, 2)``,
            with at least three points. Endpoint-gap validation must already have
            been performed by ``_assemble_outlines``.

    Returns:
        shapely.geometry.Polygon | shapely.geometry.MultiPolygon: Valid filled
        polygonal regions of the original stroke, suitable for union and scoring.

    Raises:
        ValueError: Repair produces no polygonal region with positive area, as for
            a collinear stroke or a line traced back over itself.
    """
    polygon = Polygon(points)
    if polygon.is_valid and polygon.area > 0:
        return polygon
    pending = [make_valid(polygon)]
    polygons = []
    while pending:
        part = pending.pop()
        if part.geom_type == "Polygon" and not part.is_empty and part.area > 0:
            polygons.append(part)
        elif part.geom_type in ("MultiPolygon", "GeometryCollection"):
            pending.extend(part.geoms)
    if not polygons:
        raise ValueError("Draw an outline enclosing an area before submitting.")
    return unary_union(polygons)


def drawing_to_mask(drawing, size=256, padding=12, min_area_ratio=0.0, gap_tolerance=40.0):
    """Validate, fill, filter, and normalize a canvas drawing for shape comparison.

    Accept Fabric's ``path`` and ``Path`` object types. Transform all strokes into
    common coordinates, then join nearby endpoints with ``_assemble_outlines``. Each
    completed chain must enclose positive area after automatic repair. Accepted gaps
    close with straight segments; crossings and retraced sections are repaired by
    ``_repair_outline``. Union landmasses before filtering so overlapping outlines
    form one component. Nested outlines add land rather than holes.
    Remove small disconnected components before the remaining shape is normalized.

    Args:
        drawing (dict | None): Canvas JSON containing an ``objects`` list of serialized
            freehand paths. None or an empty object list is treated as an empty drawing.
        size (int): Square mask width and height in pixels, defaulting to 256.
        padding (int): Nonnegative raster margin in pixels, defaulting to 12.
        min_area_ratio (float): Inclusive component-area threshold relative to the
            largest unioned component, in [0, 1]. Defaults to 0 (retain all). Areas
            here use Cartesian canvas units, not geographic coordinates.
        gap_tolerance (float): Maximum inter-stroke gap in canvas units, defaulting to
            40. Also increases final endpoint-closure tolerance; closure still requires
            the gap to be at most 25% of the traced length to avoid closing short arcs.

    Returns:
        numpy.ndarray: Boolean ``(size, size)`` mask of retained filled landmasses,
        centered and uniformly scaled independently of stroke color and thickness.

    Raises:
        ValueError: The cutoff or tolerance is invalid, the drawing contains unsupported
            objects, fragments cannot form a complete outline or enclose no area after
            repair, or path transformation or mask rasterization fails validation.
    """
    if not 0 <= min_area_ratio <= 1:
        raise ValueError("The landmass cutoff must be between 0 and 1.")
    paths = []
    for obj in (drawing or {}).get("objects", []):
        # Fabric 7 serializes "Path"; older canvas versions used "path".
        if str(obj.get("type", "")).lower() != "path":
            raise ValueError("Use freehand outlines to draw the country.")
        paths.append(_canvas_points(obj))
    if not paths:
        raise ValueError("Draw the country's borders before submitting.")
    polygons = _assemble_outlines(paths, join_tolerance=gap_tolerance)
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
    the final score is ``100 * IoU * border_F1**0.30 * contour_quality**0.15``.
    IoU is the primary factor; the smaller contour exponents apply gentler penalties.
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
    tolerance = 0.02 * diagonal
    precision = float(np.mean(to_country <= tolerance))
    recall = float(np.mean(to_drawing <= tolerance))
    border_match = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    mean_distance = (to_country.mean() + to_drawing.mean()) / 2
    tail_distance = max(np.percentile(to_country, 95), np.percentile(to_drawing, 95))
    contour_similarity = float(
        np.exp(-(0.5 * mean_distance + 0.5 * tail_distance) / (0.035 * diagonal))
    )

    score = 100 * overlap * border_match**0.30 * contour_similarity**0.15

    return {
        "score": float(np.clip(score, 0, 100)),
        "area_overlap": 100 * overlap,
        "border_match": 100 * border_match,
        "contour_similarity": 100 * contour_similarity,
    }


def _normalize_rotated_mask(mask, size, padding=12):
    """Fit rotated land into a square without clipping or changing its proportions.

    Args:
        mask (numpy.ndarray): Two-dimensional Boolean image containing land.
        size (int): Output side length; must exceed twice the padding plus one.
        padding (int): Output margin, defaulting to the scoring pipeline's 12 pixels.

    Returns:
        numpy.ndarray: Centered Boolean square mask. An empty input returns empty land.
        Resampling uses nearest-neighbor pixels and one shared scale for both axes.
    """
    result = np.zeros((size, size), dtype=bool)
    rows, columns = np.nonzero(mask)
    if not len(rows):
        return result
    row_slice = slice(rows.min(), rows.max() + 1)
    column_slice = slice(columns.min(), columns.max() + 1)
    crop = mask[row_slice, column_slice]
    height, width = crop.shape
    scale = (size - 2 * padding) / max(height, width)
    new_width = max(1, round(width * scale))
    new_height = max(1, round(height * scale))
    image = Image.fromarray(crop).resize(
        (new_width, new_height), resample=Image.Resampling.NEAREST
    )
    top, left = (size - new_height) // 2, (size - new_width) // 2
    result[slice(top, top + new_height), slice(left, left + new_width)] = np.asarray(image)
    return result


def smooth_coastline(mask, rounding=0):
    """Round fine border detail using Gaussian smoothing of the filled land mask.

    Args:
        mask (numpy.ndarray): Two-dimensional Boolean scoring mask.
        rounding (float): Gaussian standard deviation in normalized-mask pixels,
            from 0 to 5. Zero preserves every pixel. Larger values round corners,
            soften small bays, and can remove tiny islands or narrow features.

    Returns:
        numpy.ndarray: Boolean mask thresholded at 0.5 after smoothing, or a copy of
        the original if smoothing would remove all land. No alignment or scaling is
        performed. Apply the same setting to both masks for fair comparison.

    Raises:
        ValueError: Rounding is not finite or is outside [0, 5].
    """
    if not np.isfinite(rounding) or not 0 <= rounding <= 5:
        raise ValueError("Coastline rounding must be between 0 and 5.")
    original = np.asarray(mask, dtype=bool)
    if rounding == 0:
        return original.copy()
    smoothed = gaussian_filter(original.astype(float), rounding, mode="constant") >= 0.5
    return smoothed if smoothed.any() else original.copy()


def score_with_difficulty(drawing_mask, country_mask, allow_rotation=False, rounding=0):
    """Score optionally rounded shapes and search for the best drawing orientation.

    Smooth both masks before comparison. If rotation is enabled, retain the zero-angle
    baseline and test the entire circle at 15-degree intervals, then refine within
    15 degrees of the three best coarse candidates at one-degree intervals. This is
    an approximate angular search, not a guarantee of the continuous global optimum.
    Rotate with an expanded canvas and renormalize each candidate's bounding box so
    oblique orientations cannot clip land or change its relative overall scale.
    Reflections are never searched. Strict score improvements win ties, preserving
    the baseline when it already matches perfectly.

    Args:
        drawing_mask (numpy.ndarray): Square, normalized player mask, at least 26 pixels
            per side, with the standard 12-pixel margin used by ``drawing_to_mask``.
        country_mask (numpy.ndarray): Reference mask with identical shape and margin.
        allow_rotation (bool): Search for a better orientation when True; defaults False.
        rounding (float): Coastline smoothing strength in [0, 5], defaulting to zero.

    Returns:
        dict: ``breakdown`` contains the overall and component scores; ``drawing_mask``
        and ``country_mask`` are the exact processed masks used for the winning score;
        ``rotation_degrees`` is the counterclockwise image rotation in [0, 360).
        Rotation-enabled scores cannot fall below the corresponding zero-angle score.

    Raises:
        ValueError: Mask validation fails, inputs are not matching squares of adequate
            size, or rounding is outside its supported range.
    """
    drawing_array = np.asarray(drawing_mask)
    country_array = np.asarray(country_mask)
    if drawing_array.shape != country_array.shape:
        raise ValueError("Both masks must have the same dimensions.")
    if drawing_array.ndim != 2 or not drawing_array.size:
        raise ValueError("Scoring requires nonempty two-dimensional masks.")
    shape = drawing_array.shape
    if shape[0] != shape[1] or shape[0] < 26:
        raise ValueError("Difficulty scoring requires square masks at least 26 pixels wide.")
    if not np.isfinite(drawing_array).all() or not np.isfinite(country_array).all():
        raise ValueError("Masks must contain finite values.")
    drawing = smooth_coastline(drawing_array, rounding)
    country = smooth_coastline(country_array, rounding)
    baseline = calculate_score_breakdown(drawing, country)
    result = {
        "breakdown": baseline,
        "drawing_mask": drawing,
        "country_mask": country,
        "rotation_degrees": 0.0,
    }
    if not allow_rotation or not drawing.any() or not country.any() or baseline["score"] == 100:
        return result

    candidates = {0: baseline["score"]}

    def evaluate(angle):
        """Evaluate one integer angle once and retain a strictly better scoring mask.

        Args:
            angle (int): Counterclockwise angle, wrapped modulo 360 for deduplication.

        Returns:
            None: Updates the enclosing score cache and best-result dictionary in place.
        """
        angle %= 360
        if angle in candidates:
            return
        rotated = rotate(
            drawing.astype(np.uint8), angle, reshape=True, order=0, prefilter=False
        )
        aligned = _normalize_rotated_mask(rotated > 0, shape[0])
        breakdown = calculate_score_breakdown(aligned, country)
        candidates[angle] = breakdown["score"]
        if breakdown["score"] > result["breakdown"]["score"]:
            result.update(
                breakdown=breakdown, drawing_mask=aligned, rotation_degrees=float(angle)
            )

    for angle in range(15, 360, 15):
        evaluate(angle)
    best_coarse = sorted(candidates, key=candidates.get, reverse=True)[:3]
    for center in best_coarse:
        for angle in range(center - 15, center + 16):
            evaluate(angle)
    return result


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
