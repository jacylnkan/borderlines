"""Country names, Shapefile loading, and geographic landmass filtering."""

from collections.abc import Mapping
from typing import Any, cast

import geopandas as gpd
import pycountry
import streamlit as st
from pyproj import Geod
from shapely.geometry import MultiPolygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from src.utils.constants import MAP_DATA_PATH
from src.utils.models import LandGeometry

# This sovereignty release incorrectly identifies the UK as GA in ISO_A2_EH.
CODE_OVERRIDES: dict[str, str] = {"GB1": "GB", "IS1": "IL"}


def country_code_for_record(record: Mapping[str, Any]) -> str | None:
    """Resolve Natural Earth identifiers, preferring known fixes and ISO alpha-2 codes."""
    override = CODE_OVERRIDES.get(record.get("ADM0_A3"))
    if override:
        return override
    for field in ("ISO_A2", "ISO_A2_EH"):
        code = record.get(field)
        if isinstance(code, str) and pycountry.countries.get(alpha_2=code):
            return code
    for field in ("ISO_A3", "ADM0_A3"):
        code = record.get(field)
        if isinstance(code, str):
            country = pycountry.countries.get(alpha_3=code)
            if country:
                return str(country.alpha_2)
    return None


@st.cache_data
def load_country_geometries() -> dict[str, LandGeometry]:
    """Read the Shapefile directly and cache outlines in WGS84 longitude/latitude."""
    for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        companion = MAP_DATA_PATH.with_suffix(suffix)
        if not companion.is_file():
            raise FileNotFoundError(f"Missing map data: {companion.name}")
    frame = gpd.read_file(MAP_DATA_PATH).to_crs("EPSG:4326")
    countries: dict[str, list[LandGeometry]] = {}
    for _, record in frame.iterrows():
        code = country_code_for_record(record.to_dict())
        geometry = record.geometry
        if code and geometry is not None and not geometry.is_empty:
            countries.setdefault(code, []).append(geometry)
    return {code: cast(LandGeometry, unary_union(parts)) for code, parts in countries.items()}


def filter_landmasses(geometry: LandGeometry, min_area_ratio: float = 0.05) -> LandGeometry:
    """Keep landmasses at least this fraction of the largest one's WGS84 area.

    Zero keeps everything. This is an area filter, so large overseas territories can
    remain. Retained polygons keep their holes and original coordinates.
    """
    if not 0 <= min_area_ratio <= 1:
        raise ValueError("The landmass cutoff must be between 0 and 1.")
    if geometry.is_empty or geometry.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError("Country geometry must contain land polygons.")
    if geometry.geom_type == "Polygon" or min_area_ratio == 0:
        return geometry
    parts = list(geometry.geoms)
    geod = Geod(ellps="WGS84")
    areas = [abs(geod.geometry_area_perimeter(orient(part))[0]) for part in parts]
    cutoff = max(areas) * min_area_ratio
    retained = [part for part, area in zip(parts, areas) if area >= cutoff]
    return retained[0] if len(retained) == 1 else MultiPolygon(retained)


def format_country_name(country: pycountry.db.Country) -> str:
    """Make a readable dropdown label, including the country's flag."""
    parts = country.name.split(", ")
    name = parts[0]
    if len(parts) > 1 and country.name.split()[-1] in ("of", "the", "British", "U.S."):
        name = f"{parts[1]} {parts[0]}"
    return f"{name} {country.flag}"


def get_all_country_names() -> dict[str, str]:
    """Return supported country codes and labels, sorted by display name."""
    geometries = load_country_geometries()
    countries = [country for country in pycountry.countries if country.alpha_2 in geometries]
    countries.sort(key=format_country_name)
    return {country.alpha_2: format_country_name(country) for country in countries}
