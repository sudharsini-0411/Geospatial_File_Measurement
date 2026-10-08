"""
Unit tests for measurement service and CRS utilities.

Covers:
  - Polygon area calculation
  - MultiPolygon area calculation
  - LineString length calculation
  - MultiLineString length calculation
  - Point handling (null measurement)
  - MultiPoint handling (null measurement)
  - Unsupported geometry (GeometryCollection)
  - EPSG:4326 CRS transformation to UTM
  - Invalid geometry handling (no crash)
  - Missing CRS fallback
"""

import geopandas as gpd
import pytest
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)

from app.services.measurement import measure_geodataframe, _measure_feature
from app.utils.crs import resolve_measurement_crs, _is_metric_projected


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _single(gdf: gpd.GeoDataFrame) -> dict:
    """Runs measure_geodataframe and returns the first result."""
    results = measure_geodataframe(gdf)
    assert len(results) == 1
    return results[0]


# ---------------------------------------------------------------------------
# 8. Polygon area calculation
# ---------------------------------------------------------------------------

def test_polygon_area(gdf_polygon: gpd.GeoDataFrame) -> None:
    result = _single(gdf_polygon)
    assert result["geometry_type"] == "Polygon"
    assert result["area"] is not None
    assert result["area"] > 0
    assert result["unit"] == "square_meters"
    assert result["length"] is None
    assert result["message"] is None


# ---------------------------------------------------------------------------
# 9. MultiPolygon area calculation
# ---------------------------------------------------------------------------

def test_multipolygon_area(gdf_multipolygon: gpd.GeoDataFrame) -> None:
    result = _single(gdf_multipolygon)
    assert result["geometry_type"] == "MultiPolygon"
    assert result["area"] is not None
    assert result["area"] > 0
    assert result["unit"] == "square_meters"
    assert result["length"] is None


# ---------------------------------------------------------------------------
# 10. LineString length calculation
# ---------------------------------------------------------------------------

def test_linestring_length(gdf_linestring: gpd.GeoDataFrame) -> None:
    result = _single(gdf_linestring)
    assert result["geometry_type"] == "LineString"
    assert result["length"] is not None
    assert result["length"] > 0
    assert result["unit"] == "meters"
    assert result["area"] is None
    assert result["message"] is None


# ---------------------------------------------------------------------------
# 11. MultiLineString length calculation
# ---------------------------------------------------------------------------

def test_multilinestring_length(gdf_multilinestring: gpd.GeoDataFrame) -> None:
    result = _single(gdf_multilinestring)
    assert result["geometry_type"] == "MultiLineString"
    assert result["length"] is not None
    assert result["length"] > 0
    assert result["unit"] == "meters"
    assert result["area"] is None


# ---------------------------------------------------------------------------
# 12. Point — no measurement, informational message
# ---------------------------------------------------------------------------

def test_point_null_measurement(gdf_point: gpd.GeoDataFrame) -> None:
    result = _single(gdf_point)
    assert result["geometry_type"] == "Point"
    assert result["area"] is None
    assert result["length"] is None
    assert result["unit"] is None
    assert result["message"] is not None
    assert "point" in result["message"].lower()


def test_multipoint_null_measurement(gdf_multipoint: gpd.GeoDataFrame) -> None:
    result = _single(gdf_multipoint)
    assert result["geometry_type"] == "MultiPoint"
    assert result["area"] is None
    assert result["length"] is None
    assert result["message"] is not None


# ---------------------------------------------------------------------------
# 13. Unsupported geometry — GeometryCollection
# ---------------------------------------------------------------------------

def test_unsupported_geometry_collection(gdf_geometry_collection: gpd.GeoDataFrame) -> None:
    result = _single(gdf_geometry_collection)
    assert result["geometry_type"] == "GeometryCollection"
    assert result["area"] is None
    assert result["length"] is None
    assert result["unit"] is None
    assert result["message"] is not None
    assert "not supported" in result["message"].lower()


# ---------------------------------------------------------------------------
# 14. EPSG:4326 CRS transformation — must reproject to UTM, not use degrees
# ---------------------------------------------------------------------------

def test_epsg4326_reprojects_to_utm(gdf_polygon: gpd.GeoDataFrame) -> None:
    assert gdf_polygon.crs.to_epsg() == 4326
    resolution = resolve_measurement_crs(gdf_polygon)
    # Must NOT stay in EPSG:4326
    assert resolution.epsg != "EPSG:4326"
    # Must be a metric projected CRS
    assert _is_metric_projected(resolution.crs)
    assert not resolution.is_fallback


def test_epsg4326_area_is_in_square_meters(gdf_polygon: gpd.GeoDataFrame) -> None:
    result = _single(gdf_polygon)
    # A ~1km² polygon in degrees would be ~0.0001 sq degrees.
    # In square meters it should be in the thousands range.
    assert result["area"] > 100
    assert result["calculation_crs"] is not None
    assert result["calculation_crs"] != "EPSG:4326"


def test_already_projected_crs_used_as_is() -> None:
    gdf = gpd.GeoDataFrame(
        geometry=[Polygon([(0, 0), (1000, 0), (1000, 1000), (0, 1000)])],
        crs="EPSG:32632",  # UTM zone 32N — already metric projected
    )
    resolution = resolve_measurement_crs(gdf)
    assert resolution.epsg == "EPSG:32632"
    assert not resolution.is_fallback


def test_missing_crs_falls_back_to_3857() -> None:
    gdf = gpd.GeoDataFrame(
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])]
    )
    assert gdf.crs is None
    resolution = resolve_measurement_crs(gdf)
    assert resolution.epsg == "EPSG:3857"
    assert resolution.is_fallback


# ---------------------------------------------------------------------------
# 15. Invalid geometry — must not crash, returns result with message
# ---------------------------------------------------------------------------

def test_invalid_geometry_does_not_crash(gdf_invalid_geometry: gpd.GeoDataFrame) -> None:
    # Should not raise — invalid geometry is handled per-feature
    results = measure_geodataframe(gdf_invalid_geometry)
    assert len(results) == 1
    result = results[0]
    # Shapely may still compute area for self-intersecting polygons;
    # what matters is no exception was raised and feature_id is present
    assert "feature_id" in result
    assert result["geometry_type"] == "Polygon"


def test_mixed_geometry_batch_does_not_crash() -> None:
    """One invalid feature must not prevent other features from being measured."""
    gdf = gpd.GeoDataFrame(
        geometry=[
            Polygon([(10, 50), (10.01, 50), (10.01, 50.01), (10, 50.01)]),
            Point(10, 50),
            LineString([(10, 50), (10.01, 50)]),
        ],
        crs="EPSG:4326",
    )
    results = measure_geodataframe(gdf)
    assert len(results) == 3
    types = {r["geometry_type"] for r in results}
    assert "Polygon" in types
    assert "Point" in types
    assert "LineString" in types


# ---------------------------------------------------------------------------
# _measure_feature unit tests (pure function, no GeoDataFrame needed)
# ---------------------------------------------------------------------------

def test_measure_feature_polygon_direct() -> None:
    geom = Polygon([(0, 0), (0, 1000), (1000, 1000), (1000, 0)])
    result = _measure_feature(geom, "Polygon")
    assert result["area"] == pytest.approx(1_000_000, rel=1e-3)
    assert result["unit"] == "square_meters"


def test_measure_feature_linestring_direct() -> None:
    geom = LineString([(0, 0), (1000, 0)])
    result = _measure_feature(geom, "LineString")
    assert result["length"] == pytest.approx(1000.0, rel=1e-3)
    assert result["unit"] == "meters"


def test_measure_feature_point_returns_null() -> None:
    result = _measure_feature(Point(0, 0), "Point")
    assert result["area"] is None
    assert result["length"] is None
    assert result["message"] is not None


def test_measure_feature_unknown_returns_null() -> None:
    gc = GeometryCollection()
    result = _measure_feature(gc, "GeometryCollection")
    assert result["area"] is None
    assert result["length"] is None
    assert "not supported" in result["message"].lower()
