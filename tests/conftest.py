"""
Shared pytest fixtures.

All file fixtures are generated in-memory — no external files required.
The TestClient uses a separate file-based SQLite test database so the same
connection is shared across all requests within a session.
geo_processor is mocked in API tests to avoid driver availability issues.
"""

import io
import zipfile
from unittest.mock import patch

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient
from shapely import from_wkt
from shapely.geometry import LineString, Point, Polygon
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

# ---------------------------------------------------------------------------
# Test database — file-based so the same tables are visible across requests
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite:///./test_geospatial.db"

test_engine = create_engine(
    TEST_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Create all tables once per session; drop them after."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Mocked processing result — used by API tests to avoid driver dependency
# ---------------------------------------------------------------------------

MOCK_RESULT = {
    "feature_count": 1,
    "crs": "EPSG:4326",
    "features": [
        {
            "feature_index": 0,
            "geometry_type": "Polygon",
            "geometry": {"type": "Polygon", "coordinates": [[[10, 50], [10.01, 50], [10.01, 50.01], [10, 50.01], [10, 50]]]},
            "properties": {"name": "Test"},
            "area": 12345.67,
            "length": None,
            "unit": "square_meters",
            "message": None,
            "calculation_crs": "EPSG:32632",
            "crs_strategy": "Reprojected to UTM",
        }
    ],
}


@pytest.fixture
def mock_process_geodataframe():
    """Patches process_geodataframe so API tests don't need real geospatial drivers."""
    mock_measurements = [
        {
            "feature_id": 0,
            "geometry_type": "Polygon",
            "area": 12345.67,
            "length": None,
            "unit": "square_meters",
            "message": None,
            "calculation_crs": "EPSG:32632",
            "crs_strategy": "Reprojected to UTM",
        }
    ]
    with patch("app.services.file_processor.process_geodataframe", return_value=MOCK_RESULT):
        with patch("app.routers.files.get_measurements", return_value=mock_measurements):
            yield


# ---------------------------------------------------------------------------
# File upload fixtures
# ---------------------------------------------------------------------------

KML_CONTENT = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Test</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>10.0,50.0,0 10.01,50.0,0 10.01,50.01,0 10.0,50.01,0 10.0,50.0,0</coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""


@pytest.fixture
def kml_file() -> tuple[str, bytes, str]:
    return "test.kml", KML_CONTENT, "application/vnd.google-earth.kml+xml"


@pytest.fixture
def zip_shapefile(tmp_path) -> tuple[str, bytes, str]:
    """Generates a valid Shapefile ZIP using GeoPandas."""
    gdf = gpd.GeoDataFrame(
        {"name": ["Test"]},
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
        crs="EPSG:4326",
    )
    # Use object dtype to avoid StringDtype fiona incompatibility
    gdf["name"] = gdf["name"].astype(object)
    shp_dir = tmp_path / "shp"
    shp_dir.mkdir()
    gdf.to_file(str(shp_dir / "test.shp"))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for f in shp_dir.iterdir():
            zf.write(f, f.name)
    return "test.zip", buf.getvalue(), "application/zip"


@pytest.fixture
def invalid_file() -> tuple[str, bytes, str]:
    return "data.csv", b"col1,col2\n1,2", "text/csv"


@pytest.fixture
def empty_file() -> tuple[str, bytes, str]:
    return "empty.kml", b"", "application/vnd.google-earth.kml+xml"


# ---------------------------------------------------------------------------
# GeoDataFrame fixtures for unit tests — use from_wkt for Shapely 2.x compat
# ---------------------------------------------------------------------------

@pytest.fixture
def gdf_polygon() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        geometry=gpd.GeoSeries([Polygon([(10, 50), (10.01, 50), (10.01, 50.01), (10, 50.01)])]),
        crs="EPSG:4326",
    )


@pytest.fixture
def gdf_multipolygon() -> gpd.GeoDataFrame:
    geom = from_wkt("MULTIPOLYGON (((0 0, 1 0, 1 1, 0 1, 0 0)), ((2 2, 3 2, 3 3, 2 3, 2 2)))")
    return gpd.GeoDataFrame(geometry=gpd.GeoSeries([geom]), crs="EPSG:4326")


@pytest.fixture
def gdf_linestring() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        geometry=gpd.GeoSeries([LineString([(10, 50), (10.01, 50)])]),
        crs="EPSG:4326",
    )


@pytest.fixture
def gdf_multilinestring() -> gpd.GeoDataFrame:
    geom = from_wkt("MULTILINESTRING ((0 0, 1 0), (2 2, 3 3))")
    return gpd.GeoDataFrame(geometry=gpd.GeoSeries([geom]), crs="EPSG:4326")


@pytest.fixture
def gdf_point() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=gpd.GeoSeries([Point(10, 50)]), crs="EPSG:4326")


@pytest.fixture
def gdf_multipoint() -> gpd.GeoDataFrame:
    geom = from_wkt("MULTIPOINT ((0 0), (1 1))")
    return gpd.GeoDataFrame(geometry=gpd.GeoSeries([geom]), crs="EPSG:4326")


@pytest.fixture
def gdf_geometry_collection() -> gpd.GeoDataFrame:
    geom = from_wkt("GEOMETRYCOLLECTION (POINT (0 0), LINESTRING (0 0, 1 1))")
    return gpd.GeoDataFrame(geometry=gpd.GeoSeries([geom]), crs="EPSG:4326")


@pytest.fixture
def gdf_invalid_geometry() -> gpd.GeoDataFrame:
    """Self-intersecting bowtie polygon — is_valid == False."""
    invalid = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
    return gpd.GeoDataFrame(geometry=gpd.GeoSeries([invalid]), crs="EPSG:4326")
