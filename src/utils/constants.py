"""Defaults and project-relative paths."""

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
MAP_DATA_PATH: Path = PROJECT_ROOT / "data" / "ne_50m_admin_0_sovereignty.shp"
STYLES_PATH: Path = Path(__file__).resolve().parents[1] / "visualizations" / "styles.css"

DEFAULT_COUNTRY_CODE: str = "CA"
DEFAULT_GAP_TOLERANCE_PIXELS: float = 40.0
MASK_SIZE: int = 256
MASK_PADDING: int = 12
CANVAS_BACKGROUND_COLOUR: str = "#eee"
CANVAS_HEIGHT: int = 600
CANVAS_WIDTH: int = 700
