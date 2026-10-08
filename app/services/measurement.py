from typing import Any

import geopandas as gpd

from shapely.geometry.base import BaseGeometry
from app.utils.crs import resolve_measurement_crs

POLYGON_TYPES = {"Polygon", "MultiPolygon"}
LINESTRING_TYPES = {"LineString", "MultiLineString"}
POINT_TYPES = {"Point", "MultiPoint"}


def _null_measurement(message: str) -> dict[str, Any]:
    """Returns a null measurement dict with an explanatory message."""
    return {"area": None, "length": None, "unit": None, "message": message}


def _measure_polygon(geom: BaseGeometry) -> dict[str, Any]:
    """Returns area in square meters for Polygon or MultiPolygon."""
    return {"area": round(geom.area, 4), "length": None, "unit": "square_meters", "message": None}


def _measure_linestring(geom: BaseGeometry) -> dict[str, Any]:
    """Returns length in meters for LineString or MultiLineString."""
    return {"area": None, "length": round(geom.length, 4), "unit": "meters", "message": None}


def _measure_feature(geom: BaseGeometry, geom_type: str) -> dict[str, Any]:
    """
    Dispatches measurement by geometry type.

    - Polygon / MultiPolygon       → area in square_meters
    - LineString / MultiLineString → length in meters
    - Point / MultiPoint           → null with informational message
    - Anything else                → null with unsupported message
    """
    if geom_type in POLYGON_TYPES:
        return _measure_polygon(geom)
    if geom_type in LINESTRING_TYPES:
        return _measure_linestring(geom)
    if geom_type in POINT_TYPES:
        return _null_measurement("Measurement not applicable for Point geometry")
    return _null_measurement("Measurement not supported for this geometry type")


def measure_geodataframe(gdf: gpd.GeoDataFrame) -> list[dict[str, Any]]:
    """
    Resolves a metric projected CRS, reprojects the GeoDataFrame, then
    measures each feature independently. One bad feature never fails the batch.

    Each result dict contains:
      - feature_id      : original feature index
      - geometry_type   : Shapely geometry type string or None
      - area            : float (square_meters) or None
      - length          : float (meters) or None
      - unit            : "square_meters", "meters", or None
      - message         : explanation string when measurement is null, else None
      - calculation_crs : EPSG string of the CRS used, or None
      - crs_strategy    : human-readable CRS selection explanation
    """
    resolution = resolve_measurement_crs(gdf)

    try:
        gdf_proj = gdf.to_crs(resolution.crs)
    except Exception:
        return [
            {
                "feature_id": idx,
                "geometry_type": None,
                **_null_measurement("Reprojection failed; measurement unavailable."),
                "calculation_crs": None,
                "crs_strategy": "Reprojection failed.",
            }
            for idx in gdf.index
        ]

    results = []
    for idx, row in gdf_proj.iterrows():
        geom = row.geometry
        geom_type = geom.geom_type if (geom is not None and not geom.is_empty) else None

        entry: dict[str, Any] = {
            "feature_id": idx,
            "geometry_type": geom_type,
            "calculation_crs": resolution.epsg,
            "crs_strategy": resolution.strategy,
        }

        if geom is None or geom.is_empty or geom_type is None:
            entry.update(_null_measurement("Empty or missing geometry; measurement skipped."))
            results.append(entry)
            continue

        try:
            entry.update(_measure_feature(geom, geom_type))
        except Exception as exc:
            entry.update(_null_measurement(f"Measurement error: {exc}"))

        results.append(entry)

    return results
