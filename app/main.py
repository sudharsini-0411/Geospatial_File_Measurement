from fastapi import FastAPI
from app.database import engine
from app import models
from app.routers import files

models.Base.metadata.create_all(bind=engine)

_DESCRIPTION = """
Upload geospatial files and receive per-feature area and length measurements
in real-world metric units.

## Supported file formats

| Format | Extension | Notes |
|---|---|---|
| KML | `.kml` | Google Earth Keyhole Markup Language |
| Shapefile | `.zip` | ZIP archive containing `.shp`, `.dbf`, and `.shx` |

## Measurement units

| Geometry type | Measurement | Unit |
|---|---|---|
| `Polygon`, `MultiPolygon` | Area | `square_meters` |
| `LineString`, `MultiLineString` | Length | `meters` |
| `Point`, `MultiPoint` | — | Not applicable |

## CRS handling

Input files are **always** reprojected to a metric CRS before measurement so
that results are in real-world metres, not degrees:

1. If the input CRS is already a **metric projected CRS** (e.g. UTM), it is
   used as-is.
2. If the input CRS is **geographic** (e.g. EPSG:4326 / WGS 84), the API
   estimates the optimal local UTM zone via `estimate_utm_crs()` to minimise
   area distortion.
3. If **no CRS** is present, the API falls back to EPSG:3857 (Web Mercator)
   and marks the result as approximate.

The CRS actually used for each feature is returned in `calculation_crs`.

## File constraints

- Maximum file size: **100 MB**
- ZIP archives must contain at minimum `.shp`, `.dbf`, and `.shx` components
"""

_TAGS = [
    {
        "name": "files",
        "description": (
            "Upload geospatial files, retrieve file metadata, "
            "and fetch per-feature measurements."
        ),
    },
    {
        "name": "health",
        "description": "API liveness check.",
    },
]

app = FastAPI(
    title="Geospatial Measurement API",
    description=_DESCRIPTION,
    version="1.0.0",
    contact={"name": "Geospatial Measurement API"},
    license_info={"name": "MIT"},
    openapi_tags=_TAGS,
)

app.include_router(files.router)


@app.get(
    "/",
    tags=["health"],
    summary="Health check",
    description="Returns a confirmation message indicating the API is running.",
    responses={
        200: {
            "description": "API is running.",
            "content": {
                "application/json": {
                    "example": {"message": "Geospatial Measurement API is running"}
                }
            },
        }
    },
)
def root() -> dict[str, str]:
    return {"message": "Geospatial Measurement API is running"}
