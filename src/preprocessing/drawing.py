"""Read Fabric canvas strokes, join their endpoints, and repair filled outlines."""

from collections.abc import Sequence
from typing import cast

import numpy as np
from shapely import make_valid
from shapely.geometry import Polygon
from shapely.ops import unary_union

from src.preprocessing.masks import geometry_to_mask
from src.utils.constants import DEFAULT_GAP_TOLERANCE_PIXELS, MASK_PADDING, MASK_SIZE
from src.utils.models import Drawing, LandGeometry, Mask, Points


def _sample_path(commands: Sequence[Sequence[str | float]]) -> tuple[Points, bool]:
    """Sample Fabric M/L/Q/C/Z commands; Bezier curves use 16 points per segment."""
    points: list[Points] = []
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


def _canvas_points(obj: Drawing) -> Points:
    """Apply Fabric transforms and convert downward canvas y to upward Cartesian y."""
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
    # Fabric left/top include line thickness; recover the path's centerline position.
    center = np.array([obj.get("left", 0), obj.get("top", 0)], dtype=float)
    center -= rotation @ (origin * (dimensions + obj.get("strokeWidth", 1)) * scale)
    flips = np.array([-1 if obj.get("flipX") else 1, -1 if obj.get("flipY") else 1])
    points = ((points - offset) * scale * flips) @ rotation.T + center
    if not np.isfinite(points).all():
        raise ValueError("The drawing contains invalid coordinates.")
    if closed and not np.array_equal(points[0], points[-1]):
        points = np.vstack((points, points[0]))
    points[:, 1] *= -1
    return points


def _repair_outline(points: Points) -> LandGeometry:
    """Keep filled regions from crossed strokes and discard collapsed retraced lines."""
    polygon = Polygon(points)
    if polygon.is_valid and polygon.area > 0:
        return polygon
    pending = [make_valid(polygon)]
    polygons: list[Polygon] = []
    while pending:
        part = pending.pop()
        if part.geom_type == "Polygon" and not part.is_empty and part.area > 0:
            polygons.append(part)
        elif part.geom_type in ("MultiPolygon", "GeometryCollection"):
            pending.extend(part.geoms)
    if not polygons:
        raise ValueError("Draw an outline enclosing an area before submitting.")
    return cast(LandGeometry, unary_union(polygons))


def _assemble_outlines(
    paths: Sequence[Points], join_tolerance: float = DEFAULT_GAP_TOLERANCE_PIXELS
) -> list[LandGeometry]:
    """Join the nearest endpoints, reversing strokes as needed, then fill closed chains.

    Closed islands win ties. Closure allows a 20%-diagonal gap, at least the joining
    tolerance, but no more than 25% of the traced length. This avoids filling short arcs.
    """
    if not np.isfinite(join_tolerance) or join_tolerance < 0:
        raise ValueError("Gap tolerance must be finite and nonnegative.")
    remaining = list(paths)
    polygons: list[LandGeometry] = []
    while remaining:
        best_distance = float("inf")
        connection: tuple[int, int, int, int] | None = None
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
                    connection = (first, second, int(a_end), int(b_end))
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


def drawing_to_mask(
    drawing: Drawing | None,
    size: int = MASK_SIZE,
    padding: int = MASK_PADDING,
    min_area_ratio: float = 0.0,
    gap_tolerance: float = DEFAULT_GAP_TOLERANCE_PIXELS,
) -> Mask:
    """Join and repair canvas strokes, remove small landmasses, and normalize the mask."""
    if not 0 <= min_area_ratio <= 1:
        raise ValueError("The landmass cutoff must be between 0 and 1.")
    paths: list[Points] = []
    for obj in (drawing or {}).get("objects", []):
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
    return geometry_to_mask(cast(LandGeometry, geometry), size, padding)
