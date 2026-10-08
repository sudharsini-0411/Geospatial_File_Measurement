from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely.geometry.base import BaseGeometry

from app.utils.crs import crs_to_string
from app.services.measurement import measure_geodataframe


def _find_shp(directory: Path) -> Path:
    """Locates the first .shp file inside an extracted ZIP directory."""
    matches = list(directory.rglob("*.shp"))
    if not matches:
        raise ValueError("No .shp file found in the extracted ZIP.")
    return matches[0]


def _load_geodataframe(saved_path: str) -> gpd.GeoDataFrame:
    """
    Reads a KML or Shapefile into a GeoDataFrame.
    Raises ValueError on unsupported extension or read failure.
    """
    path = Path(saved_path).resolve()
    uploads_root = (Path("uploads")).resolve()
    if not path.is_relative_to(uploads_root):
        raise ValueError("File path is outside the uploads directory.")

    ext = path.suffix.lower()
    file_dir = path.parent

    try:
        if ext == ".kml":
            return gpd.read_file(str(path), driver="KML")
        if ext == ".zip":
            return gpd.read_file(str(_find_shp(file_dir)))
        raise ValueError(f"Unsupported extension: {ext}")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Failed to read geospatial file: {e}")


def _serialize_geometry(geom: BaseGeometry | None) -> dict[str, Any] | None:
    """Converts a Shapely geometry to a GeoJSON-compatible dict."""
    if geom is None or geom.is_empty:
        return None
    return geom.__geo_interface__


def _extract_features(
    gdf: gpd.GeoDataFrame, measurements: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merges GeoDataFrame rows with their corresponding measurements."""
    measurement_by_id = {m["feature_id"]: m for m in measurements}
    features = []
    for idx, row in gdf.iterrows():
        props = {
            col: row[col]
            for col in gdf.columns
            if col != "geometry" and row[col] is not None
        }
        m = measurement_by_id.get(idx, {})
        features.append(
            {
                "feature_index": idx,
                "geometry_type": row.geometry.geom_type if row.geometry else None,
                "geometry": _serialize_geometry(row.geometry),
                "properties": props,
                "area": m.get("area"),
                "length": m.get("length"),
                "unit": m.get("unit"),
                "message": m.get("message"),
                "calculation_crs": m.get("calculation_crs"),
                "crs_strategy": m.get("crs_strategy"),
            }
        )
    return features


def get_measurements(saved_path: str) -> list[dict[str, Any]]:
    """
    Loads the file and returns per-feature measurements only.
    No geometry or properties — focused for the measurements endpoint.
    Raises ValueError on read failure or empty file.
    """
    gdf = _load_geodataframe(saved_path)
    if gdf.empty:
        raise ValueError("The geospatial file contains no features.")
    return measure_geodataframe(gdf)


def process_geodataframe(saved_path: str) -> dict[str, Any]:
    """
    Loads a KML or Shapefile, runs measurements, and returns feature count,
    CRS string, and enriched features list.
    Raises ValueError on any processing failure.
    """
    gdf = _load_geodataframe(saved_path)
    if gdf.empty:
        raise ValueError("The geospatial file contains no features.")

    measurements = measure_geodataframe(gdf)
    return {
        "feature_count": len(gdf),
        "crs": crs_to_string(gdf.crs),
        "features": _extract_features(gdf, measurements),
    }
