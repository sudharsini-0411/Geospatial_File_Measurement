"""
CRS Strategy
============
EPSG:4326 (WGS 84) is a *geographic* CRS — coordinates are in decimal degrees
of latitude and longitude on an ellipsoid. Degrees are not a unit of length or
area: one degree of longitude near the equator is ~111 km, but near the poles
it approaches zero. Calling `.area` or `.length` on Shapely geometries in
EPSG:4326 returns values in square degrees or degrees, which are physically
meaningless and wildly inaccurate for any real-world measurement.

Correct approach:
  1. If the input CRS is geographic (e.g. EPSG:4326), reproject to a metric
     projected CRS before measuring.
  2. Prefer a local UTM zone derived via GeoPandas `estimate_utm_crs()`, which
     minimises distortion for the specific geographic area of the data.
  3. If the input CRS is already a metric projected CRS, use it as-is.
  4. If the CRS is projected but uses non-metric units (e.g. feet), reproject
     to UTM to normalise output to square meters.
  5. If no CRS is present at all, fall back to EPSG:3857 (Web Mercator) and
     flag it — results will be approximate near the poles.
"""

from dataclasses import dataclass

import geopandas as gpd
from pyproj import CRS


@dataclass
class CRSResolution:
    """
    Carries the resolved projected CRS and metadata about how it was chosen.
    Passed to the measurement service so it can report the calculation CRS.
    """
    crs: CRS
    epsg: str | None        # e.g. "EPSG:32634"
    strategy: str           # human-readable description of how CRS was chosen
    is_fallback: bool       # True when no reliable CRS was available


def _is_metric_projected(crs: CRS) -> bool:
    """Returns True if the CRS is projected and uses metre as its linear unit."""
    if not crs.is_projected:
        return False
    unit = crs.axis_info[0].unit_name.lower()
    return "metre" in unit or "meter" in unit


def _epsg_string(crs: CRS) -> str | None:
    try:
        code = crs.to_epsg()
        return f"EPSG:{code}" if code else None
    except Exception:
        return None


def resolve_measurement_crs(gdf: gpd.GeoDataFrame) -> CRSResolution:
    """
    Inspects the GeoDataFrame CRS and returns a CRSResolution with the best
    metric projected CRS to use for area/length calculations.

    Decision order:
      1. No CRS          → EPSG:3857 fallback (is_fallback=True)
      2. Already metric projected → use as-is
      3. Geographic or non-metric projected → estimate_utm_crs() for local UTM
    """
    if gdf.crs is None:
        # No CRS attached — we cannot know the true projection.
        # EPSG:3857 (Web Mercator) uses metres but distorts area away from equator.
        fallback = CRS.from_epsg(3857)
        return CRSResolution(
            crs=fallback,
            epsg="EPSG:3857",
            strategy="No CRS found; fell back to EPSG:3857 (Web Mercator). Results are approximate.",
            is_fallback=True,
        )

    if _is_metric_projected(gdf.crs):
        # Already in a metric projected CRS — safe to measure directly.
        return CRSResolution(
            crs=gdf.crs,
            epsg=_epsg_string(gdf.crs),
            strategy=f"Input CRS is already metric projected ({gdf.crs.name}); used as-is.",
            is_fallback=False,
        )

    # Geographic CRS (e.g. EPSG:4326) or projected with non-metric units.
    # Use GeoPandas estimate_utm_crs() which picks the optimal local UTM zone
    # based on the actual extent of the data — minimises area distortion.
    try:
        utm_crs = gdf.estimate_utm_crs()
        strategy = (
            f"Input CRS '{gdf.crs.name}' is not metric projected; "
            f"reprojected to local UTM ({utm_crs.name}) via estimate_utm_crs()."
        )
        return CRSResolution(
            crs=utm_crs,
            epsg=_epsg_string(utm_crs),
            strategy=strategy,
            is_fallback=False,
        )
    except Exception as e:
        # estimate_utm_crs() can fail for data outside normal bounds (e.g. poles).
        # Fall back to EPSG:3857 rather than crashing.
        fallback = CRS.from_epsg(3857)
        return CRSResolution(
            crs=fallback,
            epsg="EPSG:3857",
            strategy=f"UTM estimation failed ({e}); fell back to EPSG:3857.",
            is_fallback=True,
        )


def crs_to_string(crs: CRS | None) -> str | None:
    """Converts a pyproj CRS object to a human-readable EPSG string or name."""
    if crs is None:
        return None
    try:
        code = crs.to_epsg()
        return f"EPSG:{code}" if code else crs.name
    except Exception:
        return str(crs)
