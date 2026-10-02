"""Convert outlines into comparable images and render score overlays."""

from typing import cast

import numpy as np
from PIL import Image as PILImage
from PIL import ImageDraw
from pyproj import CRS, Transformer
from shapely.geometry import LinearRing
from shapely.ops import transform

from src.utils.constants import MASK_PADDING, MASK_SIZE
from src.utils.models import Image, LandGeometry, Mask


def geometry_to_mask(
    geometry: LandGeometry, size: int = MASK_SIZE, padding: int = MASK_PADDING
) -> Mask:
    """Center and uniformly scale Cartesian land into a Boolean mask, preserving holes."""
    if geometry.is_empty or geometry.area <= 0:
        raise ValueError("Draw an outline enclosing an area before submitting.")
    if size <= 2 * padding or padding < 0:
        raise ValueError("The mask must have space inside its padding.")
    if not np.isfinite(geometry.bounds).all():
        raise ValueError("The outline contains invalid coordinates.")
    min_x, min_y, max_x, max_y = geometry.bounds
    width, height = max_x - min_x, max_y - min_y
    scale = (size - 1 - 2 * padding) / max(width, height)
    offset_x = (size - 1 - width * scale) / 2
    offset_y = (size - 1 - height * scale) / 2

    def to_pixels(ring: LinearRing) -> list[tuple[float, float]]:
        """Flip Cartesian y upward into image rows downward."""
        return [
            (offset_x + (x - min_x) * scale, offset_y + (max_y - y) * scale)
            for x, y in ring.coords
        ]

    polygons = [geometry] if geometry.geom_type == "Polygon" else geometry.geoms
    mask = np.zeros((size, size), dtype=bool)
    for polygon in polygons:
        image = PILImage.new("L", (size, size), 0)
        draw = ImageDraw.Draw(image)
        draw.polygon(to_pixels(polygon.exterior), fill=255)
        for hole in polygon.interiors:
            draw.polygon(to_pixels(hole), fill=0)
        mask |= np.asarray(image) > 0
    return mask


def country_to_mask(
    geometry: LandGeometry, size: int = MASK_SIZE, padding: int = MASK_PADDING
) -> Mask:
    """Project WGS84 land onto a local equal-area map, then normalize it for scoring."""
    parts = [geometry] if geometry.geom_type == "Polygon" else geometry.geoms
    center = max(parts, key=lambda part: part.area).representative_point()
    local_crs = CRS.from_proj4(
        f"+proj=laea +lat_0={center.y} +lon_0={center.x} +datum=WGS84 +units=m"
    )
    transformer = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)
    projected = cast(LandGeometry, transform(transformer.transform, geometry))
    return geometry_to_mask(projected, size, padding)


def normalize_rotated_mask(mask: Mask, size: int, padding: int = MASK_PADDING) -> Mask:
    """Refit rotated land without clipping or stretching its aspect ratio."""
    result = np.zeros((size, size), dtype=bool)
    rows, columns = np.nonzero(mask)
    if not len(rows):
        return result
    crop = mask[slice(rows.min(), rows.max() + 1), slice(columns.min(), columns.max() + 1)]
    height, width = crop.shape
    scale = (size - 2 * padding) / max(height, width)
    new_width, new_height = max(1, round(width * scale)), max(1, round(height * scale))
    image = PILImage.fromarray(crop).resize(
        (new_width, new_height), resample=PILImage.Resampling.NEAREST
    )
    top, left = (size - new_height) // 2, (size - new_width) // 2
    result[slice(top, top + new_height), slice(left, left + new_width)] = np.asarray(image)
    return result


def create_overlay(drawing_mask: Mask, country_mask: Mask) -> Image:
    """Show reference-only land in blue, drawing-only in orange, and overlap in purple."""
    overlay = np.full((*country_mask.shape, 3), 245, dtype=np.uint8)
    overlay[country_mask] = (59, 130, 246)
    overlay[drawing_mask] = (249, 150, 55)
    overlay[np.logical_and(drawing_mask, country_mask)] = (147, 80, 190)
    return overlay
