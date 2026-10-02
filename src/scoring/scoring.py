"""Compare filled shapes, with optional coastline rounding and rotation matching."""

import numpy as np
from scipy.ndimage import binary_erosion, distance_transform_edt, gaussian_filter, rotate

from src.preprocessing.masks import normalize_rotated_mask
from src.utils.models import Comparison, Mask, ScoreBreakdown

BORDER_TOLERANCE_RATIO: float = 0.02
CONTOUR_DISTANCE_RATIO: float = 0.035
BORDER_WEIGHT: float = 0.30
CONTOUR_WEIGHT: float = 0.15


def _validate_masks(drawing_mask: Mask, country_mask: Mask) -> tuple[Mask, Mask]:
    """Require matching, finite, nonempty 2D arrays and convert them to Boolean land."""
    drawing = np.asarray(drawing_mask)
    country = np.asarray(country_mask)
    if drawing.shape != country.shape:
        raise ValueError("Both masks must have the same dimensions.")
    if drawing.ndim != 2 or not drawing.size:
        raise ValueError("Scoring requires nonempty two-dimensional masks.")
    if not np.isfinite(drawing).all() or not np.isfinite(country).all():
        raise ValueError("Masks must contain finite values.")
    return drawing.astype(bool), country.astype(bool)


def calculate_score_breakdown(drawing_mask: Mask, country_mask: Mask) -> ScoreBreakdown:
    """Combine area overlap with gentler border-match and contour-distance penalties.

    Border match measures coverage within 2% of the image diagonal. Contour similarity
    measures mean distance and larger (95th-percentile) errors in both directions.
    Score = 100 × IoU × border_match^0.30 × contour_similarity^0.15, using fractions.
    """
    drawing, country = _validate_masks(drawing_mask, country_mask)
    if not drawing.any() or not country.any():
        return dict(score=0.0, area_overlap=0.0, border_match=0.0, contour_similarity=0.0)
    overlap = float(
        np.logical_and(drawing, country).sum() / np.logical_or(drawing, country).sum()
    )
    drawing_border = drawing & ~binary_erosion(drawing, border_value=0)
    country_border = country & ~binary_erosion(country, border_value=0)
    to_country = distance_transform_edt(~country_border)[drawing_border]
    to_drawing = distance_transform_edt(~drawing_border)[country_border]
    diagonal = float(np.hypot(*country.shape))
    tolerance = BORDER_TOLERANCE_RATIO * diagonal
    precision = float(np.mean(to_country <= tolerance))
    recall = float(np.mean(to_drawing <= tolerance))
    border_match = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    mean_distance = (to_country.mean() + to_drawing.mean()) / 2
    tail_distance = max(np.percentile(to_country, 95), np.percentile(to_drawing, 95))
    contour_similarity = float(
        np.exp(
            -(0.5 * mean_distance + 0.5 * tail_distance) / (CONTOUR_DISTANCE_RATIO * diagonal)
        )
    )
    score = 100 * overlap * border_match**BORDER_WEIGHT * contour_similarity**CONTOUR_WEIGHT
    return {
        "score": float(np.clip(score, 0, 100)),
        "area_overlap": 100 * overlap,
        "border_match": 100 * border_match,
        "contour_similarity": 100 * contour_similarity,
    }


def calculate_accuracy(drawing_mask: Mask, country_mask: Mask) -> float:
    """Return only the overall score, from 0 to 100."""
    return calculate_score_breakdown(drawing_mask, country_mask)["score"]


def smooth_coastline(mask: Mask, rounding: float = 0) -> Mask:
    """Soften fine border detail with Gaussian smoothing; zero keeps every pixel.

    Strength is 0–5 normalized-mask pixels. Retain the original if all land would vanish.
    """
    if not np.isfinite(rounding) or not 0 <= rounding <= 5:
        raise ValueError("Coastline rounding must be between 0 and 5.")
    original = np.asarray(mask, dtype=bool)
    if rounding == 0:
        return original.copy()
    smoothed = gaussian_filter(original.astype(float), rounding, mode="constant") >= 0.5
    return smoothed if smoothed.any() else original.copy()


def score_with_difficulty(
    drawing_mask: Mask,
    country_mask: Mask,
    allow_rotation: bool = False,
    rounding: float = 0,
) -> Comparison:
    """Round both masks, optionally align the drawing, and return the exact scored shapes.

    Rotation searches every 15 degrees, then refines three best neighborhoods at
    one-degree intervals. It never mirrors shapes or scores below the unrotated baseline.
    """
    drawing, country = _validate_masks(drawing_mask, country_mask)
    size = drawing.shape[0]
    if size != drawing.shape[1] or size < 26:
        raise ValueError("Difficulty scoring requires square masks at least 26 pixels wide.")
    drawing = smooth_coastline(drawing, rounding)
    country = smooth_coastline(country, rounding)
    baseline = calculate_score_breakdown(drawing, country)
    result: Comparison = {
        "breakdown": baseline,
        "drawing_mask": drawing,
        "country_mask": country,
        "rotation_degrees": 0.0,
    }
    if not allow_rotation or not drawing.any() or not country.any() or baseline["score"] == 100:
        return result
    candidates: dict[int, float] = {0: baseline["score"]}

    def evaluate(angle: int) -> None:
        """Evaluate an angle once and retain it only if it beats the current best."""
        angle %= 360
        if angle in candidates:
            return
        rotated = rotate(
            drawing.astype(np.uint8), angle, reshape=True, order=0, prefilter=False
        )
        aligned = normalize_rotated_mask(rotated > 0, size)
        breakdown = calculate_score_breakdown(aligned, country)
        candidates[angle] = breakdown["score"]
        if breakdown["score"] > result["breakdown"]["score"]:
            result["breakdown"] = breakdown
            result["drawing_mask"] = aligned
            result["rotation_degrees"] = float(angle)

    for angle in range(15, 360, 15):
        evaluate(angle)
    best_coarse = sorted(candidates, key=lambda angle: candidates[angle], reverse=True)[:3]
    for center in best_coarse:
        for angle in range(center - 15, center + 16):
            evaluate(angle)
    return result
