import geopandas as gpd
import pycountry
import streamlit as st
from pyproj import Geod
from shapely.geometry import MultiPolygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from src.utils.constants import MAP_DATA_PATH

# This sovereignty release uses aggregate codes; its UK ISO_A2_EH is incorrectly GA.
CODE_OVERRIDES = {"GB1": "GB", "IS1": "IL"}


def filter_landmasses(geometry, min_area_ratio=0.05):
    """Remove landmasses smaller than a fraction of the largest geographic landmass.

    Measure each component on the WGS84 ellipsoid rather than in square degrees.
    Ring orientation is normalized for area measurement so holes subtract from land
    area. Retained polygons keep their original coordinates and holes. This is an
    area-only filter: a large overseas territory can qualify regardless of distance.

    Args:
        geometry (shapely.geometry.Polygon | shapely.geometry.MultiPolygon): Nonempty,
            valid country geometry in WGS84 longitude/latitude coordinates.
        min_area_ratio (float): Inclusive area threshold relative to the largest
            component, between 0 and 1. Defaults to 0.05 (5%). Zero retains everything;
            one retains only components tied for largest area.

    Returns:
        shapely.geometry.Polygon | shapely.geometry.MultiPolygon: Retained landmasses
        in WGS84 coordinates. A single retained component is returned as a Polygon.
        A single-polygon input or a zero cutoff returns the input geometry directly.

    Raises:
        ValueError: The ratio is outside [0, 1], or geometry is empty or nonpolygonal.
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


def country_code_for_record(record):
    """Resolve a Natural Earth attribute record to a supported ISO alpha-2 code.

    Apply known ``ADM0_A3`` overrides first, including the sovereignty dataset's UK
    code correction. Then try ``ISO_A2`` and ``ISO_A2_EH`` against pycountry, followed
    by alpha-3 lookup of ``ISO_A3`` and ``ADM0_A3``. Missing fields, nonstring values,
    and unrecognized identifiers such as ``-99`` are skipped.

    Args:
        record (Mapping | pandas.Series): Dataset attributes supporting ``get``.

    Returns:
        str | None: Recognized two-letter country code, or None when no supported
        code can be resolved. The record is not modified.
    """
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
                return country.alpha_2
    return None


@st.cache_data
def load_country_geometries():
    """Load and cache country geometries directly from the configured Shapefile.

    Read ``MAP_DATA_PATH`` with GeoPandas after checking for all five companion files
    (.shp, .shx, .dbf, .prj, and .cpg). Reproject to EPSG:4326 in memory, resolve each
    feature's ISO code, and union features sharing a code. Unmapped records and null
    or empty geometries are skipped. No GeoJSON file is created.

    Returns:
        dict[str, shapely.geometry.base.BaseGeometry]: ISO alpha-2 codes mapped to
        WGS84 country geometries, including all mapped landmasses before filtering.
        Streamlit caches the result across reruns; clear the function's cache after
        replacing data files because file contents are not part of the cache key.

    Raises:
        FileNotFoundError: Any required Shapefile companion is absent.
        ValueError: GeoPandas cannot interpret or transform the coordinate system.
            File-reader and geometry-union errors also propagate to the caller.
    """
    for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        if not MAP_DATA_PATH.with_suffix(suffix).is_file():
            raise FileNotFoundError(
                f"Missing map data: {MAP_DATA_PATH.with_suffix(suffix).name}"
            )
    frame = gpd.read_file(MAP_DATA_PATH).to_crs("EPSG:4326")
    countries = {}
    for _, record in frame.iterrows():
        code = country_code_for_record(record)
        geometry = record.geometry
        if code and geometry is not None and not geometry.is_empty:
            countries.setdefault(code, []).append(geometry)
    return {code: unary_union(parts) for code, parts in countries.items()}
