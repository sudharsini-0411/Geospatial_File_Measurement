from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class FileRecordResponse(BaseModel):
    id: str = Field(
        ...,
        description="Unique UUID assigned to the uploaded file.",
        examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    )
    filename: str = Field(
        ...,
        description="Original filename as provided during upload.",
        examples=["boundaries.kml"],
    )
    feature_count: Optional[int] = Field(
        None,
        description="Number of geospatial features found in the file. `null` if processing has not completed.",
        examples=[4],
    )
    crs: Optional[str] = Field(
        None,
        description=(
            "Coordinate Reference System of the source file as an EPSG string or CRS name. "
            "`null` if the file carries no CRS information."
        ),
        examples=["EPSG:4326"],
    )
    status: str = Field(
        ...,
        description="Processing status. One of `processing`, `completed`, or `failed`.",
        examples=["completed"],
    )
    created_at: datetime = Field(
        ...,
        description="UTC timestamp of when the file was uploaded.",
        examples=["2024-06-01T12:00:00Z"],
    )

    model_config = {"from_attributes": True}


class FeatureSchema(BaseModel):
    feature_index: int = Field(
        ...,
        description="Zero-based index of this feature within the source file.",
        examples=[0],
    )
    geometry_type: Optional[str] = Field(
        None,
        description=(
            "Shapely geometry type string. One of `Polygon`, `MultiPolygon`, "
            "`LineString`, `MultiLineString`, `Point`, `MultiPoint`, "
            "`GeometryCollection`, or `null` for empty geometries."
        ),
        examples=["Polygon"],
    )
    geometry: Optional[dict[str, Any]] = Field(
        None,
        description="GeoJSON-compatible geometry object. `null` for empty or missing geometries.",
        examples=[
            {
                "type": "Polygon",
                "coordinates": [
                    [[10.0, 50.0], [10.01, 50.0], [10.01, 50.01], [10.0, 50.01], [10.0, 50.0]]
                ],
            }
        ],
    )
    properties: dict[str, Any] = Field(
        ...,
        description="Attribute properties attached to the feature in the source file.",
        examples=[{"name": "Central Park", "type": "park"}],
    )
    area: Optional[float] = Field(
        None,
        description=(
            "Area of the feature in **square metres**, reprojected to a metric CRS. "
            "Populated for `Polygon` and `MultiPolygon` geometries only. `null` otherwise."
        ),
        examples=[785000.5],
    )
    length: Optional[float] = Field(
        None,
        description=(
            "Length of the feature in **metres**, reprojected to a metric CRS. "
            "Populated for `LineString` and `MultiLineString` geometries only. `null` otherwise."
        ),
        examples=[2340.75],
    )
    unit: Optional[str] = Field(
        None,
        description=(
            "Unit of the reported measurement. "
            "`square_meters` for area, `meters` for length, `null` when no measurement applies."
        ),
        examples=["square_meters"],
    )
    message: Optional[str] = Field(
        None,
        description=(
            "Informational or warning message. Present when measurement is not applicable "
            "(e.g. Point geometry) or when an error occurred during measurement. `null` on success."
        ),
        examples=["Measurement not applicable for Point geometry"],
    )
    calculation_crs: Optional[str] = Field(
        None,
        description=(
            "EPSG string of the projected CRS used for this feature's measurement. "
            "Will differ from the source CRS when reprojection was applied."
        ),
        examples=["EPSG:32632"],
    )
    crs_strategy: Optional[str] = Field(
        None,
        description="Human-readable explanation of how the calculation CRS was selected.",
        examples=[
            "Input CRS 'WGS 84' is not metric projected; "
            "reprojected to local UTM (WGS 84 / UTM zone 32N) via estimate_utm_crs()."
        ],
    )


class MeasurementItem(BaseModel):
    feature_id: int = Field(
        ...,
        description="Zero-based index of the feature within the source file.",
        examples=[0],
    )
    geometry_type: Optional[str] = Field(
        None,
        description=(
            "Shapely geometry type string. One of `Polygon`, `MultiPolygon`, "
            "`LineString`, `MultiLineString`, `Point`, `MultiPoint`, "
            "`GeometryCollection`, or `null` for empty geometries."
        ),
        examples=["LineString"],
    )
    area: Optional[float] = Field(
        None,
        description="Area in **square metres**. Populated for polygon geometries only.",
        examples=[None],
    )
    length: Optional[float] = Field(
        None,
        description="Length in **metres**. Populated for line geometries only.",
        examples=[2340.75],
    )
    unit: Optional[str] = Field(
        None,
        description="`square_meters`, `meters`, or `null` when measurement is not applicable.",
        examples=["meters"],
    )
    message: Optional[str] = Field(
        None,
        description="Present when measurement could not be computed; `null` on success.",
        examples=[None],
    )
    calculation_crs: Optional[str] = Field(
        None,
        description="EPSG string of the projected CRS used for measurement.",
        examples=["EPSG:32632"],
    )

    @classmethod
    def from_dict(cls, m: dict[str, Any]) -> "MeasurementItem":
        """Constructs a MeasurementItem from a raw measurement dict."""
        return cls(
            feature_id=m["feature_id"],
            geometry_type=m.get("geometry_type"),
            area=m.get("area"),
            length=m.get("length"),
            unit=m.get("unit"),
            message=m.get("message"),
            calculation_crs=m.get("calculation_crs"),
        )


class MeasurementsResponse(BaseModel):
    file_id: str = Field(
        ...,
        description="UUID of the file these measurements belong to.",
        examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    )
    measurements: list[MeasurementItem] = Field(
        ...,
        description="One entry per feature in the source file, in original feature order.",
    )


class ProcessingResultResponse(BaseModel):
    id: str = Field(
        ...,
        description="UUID assigned to this upload. Use it to query metadata and measurements.",
        examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    )
    filename: str = Field(
        ...,
        description="Original filename as provided during upload.",
        examples=["regions.kml"],
    )
    status: str = Field(
        ...,
        description="Always `completed` in a successful upload response.",
        examples=["completed"],
    )
    feature_count: int = Field(
        ...,
        description="Total number of geospatial features parsed from the file.",
        examples=[3],
    )
    crs: Optional[str] = Field(
        None,
        description=(
            "CRS of the source file as an EPSG string or CRS name. "
            "`null` if the file carries no CRS information."
        ),
        examples=["EPSG:4326"],
    )
    features: list[FeatureSchema] = Field(
        ...,
        description=(
            "Full feature list including geometry, source properties, "
            "and computed measurements."
        ),
    )
