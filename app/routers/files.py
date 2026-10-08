from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FileRecord
from app.schemas import FileRecordResponse, MeasurementItem, MeasurementsResponse, ProcessingResultResponse
from app.services.file_processor import get_file_record, process_file, save_upload
from app.services.geo_processor import get_measurements

router = APIRouter(prefix="/api/files", tags=["files"])

_404 = {
    "description": "File not found.",
    "content": {
        "application/json": {
            "example": {"detail": "File '3fa85f64-5717-4562-b3fc-2c963f66afa6' not found."}
        }
    },
}

_400_upload = {
    "description": (
        "Invalid upload. Possible causes:\n\n"
        "- Unsupported file extension (only `.kml` and `.zip` are accepted)\n"
        "- Empty file\n"
        "- File exceeds the 100 MB size limit\n"
        "- ZIP archive contains path-traversal entries\n"
        "- ZIP archive is missing required Shapefile components (`.shp`, `.dbf`, `.shx`)"
    ),
    "content": {
        "application/json": {
            "examples": {
                "unsupported_extension": {
                    "summary": "Unsupported file type",
                    "value": {"detail": "Unsupported file type '.csv'. Allowed: ['.kml', '.zip']"},
                },
                "empty_file": {
                    "summary": "Empty file",
                    "value": {"detail": "Uploaded file is empty."},
                },
                "missing_shapefile_components": {
                    "summary": "Incomplete Shapefile ZIP",
                    "value": {"detail": "ZIP is missing required Shapefile components: ['.dbf', '.shx']"},
                },
            }
        }
    },
}

_422_processing = {
    "description": (
        "Processing failed. The file was accepted but could not be parsed or "
        "contained no readable features."
    ),
    "content": {
        "application/json": {
            "example": {"detail": "The geospatial file contains no features."}
        }
    },
}

_FILE_ID_PATH = Path(
    ...,
    description="UUID returned by the upload endpoint.",
    examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
)


@router.post(
    "/",
    response_model=ProcessingResultResponse,
    status_code=201,
    summary="Upload a geospatial file",
    description=(
        "Upload a **KML** (`.kml`) or **Shapefile ZIP** (`.zip`) and receive "
        "per-feature measurements in a single response.\n\n"
        "**Accepted formats**\n\n"
        "- `.kml` — Google Earth Keyhole Markup Language\n"
        "- `.zip` — ZIP archive containing at minimum `.shp`, `.dbf`, and `.shx`\n\n"
        "**What happens on upload**\n\n"
        "1. The file is validated (extension, size, ZIP integrity).\n"
        "2. Features are parsed with GeoPandas.\n"
        "3. The source CRS is inspected; if it is geographic (e.g. EPSG:4326) the "
        "data is reprojected to the optimal local UTM zone before measuring.\n"
        "4. Area (`square_meters`) or length (`meters`) is computed per feature.\n"
        "5. The assigned `id` can be used to re-fetch metadata or measurements later.\n\n"
        "**Size limit:** 100 MB."
    ),
    responses={
        201: {"description": "File processed successfully. Measurements are included in the response."},
        400: _400_upload,
        422: _422_processing,
    },
)
async def upload_file(file: UploadFile = File(
    ...,
    description=(
        "Geospatial file to upload. Must be `.kml` or a `.zip` Shapefile archive. "
        "Maximum size 100 MB."
    ),
), db: Session = Depends(get_db)):
    file_id, filename, saved_path = await save_upload(file)

    record = FileRecord(
        id=file_id,
        filename=filename,
        file_path=saved_path,
        status="processing",
        created_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.commit()

    result = process_file(record, db)

    return ProcessingResultResponse(
        id=file_id,
        filename=filename,
        status="completed",
        feature_count=result["feature_count"],
        crs=result["crs"],
        features=result["features"],
    )


@router.get(
    "/{file_id}/",
    response_model=FileRecordResponse,
    summary="Get file metadata",
    description=(
        "Retrieve stored metadata for a previously uploaded file by its UUID.\n\n"
        "Returns the original filename, feature count, source CRS, processing status, "
        "and upload timestamp. Does **not** return geometry or measurements — "
        "use `GET /api/files/{file_id}/measurements/` for those."
    ),
    responses={
        200: {"description": "File metadata retrieved successfully."},
        404: _404,
    },
)
def get_file(
    file_id: str = _FILE_ID_PATH,
    db: Session = Depends(get_db),
):
    return get_file_record(file_id, db)


@router.get(
    "/{file_id}/measurements/",
    response_model=MeasurementsResponse,
    summary="Get per-feature measurements",
    description=(
        "Return area or length measurements for every feature in an uploaded file.\n\n"
        "**Measurement rules**\n\n"
        "| Geometry | Field populated | Unit |\n"
        "|---|---|---|\n"
        "| `Polygon`, `MultiPolygon` | `area` | `square_meters` |\n"
        "| `LineString`, `MultiLineString` | `length` | `meters` |\n"
        "| `Point`, `MultiPoint` | neither | — |\n"
        "| Other / unsupported | neither | — |\n\n"
        "**CRS note:** measurements are always computed in a metric projected CRS "
        "(local UTM when possible). The CRS used is reported in `calculation_crs` "
        "on each item.\n\n"
        "Returns `404` if the `file_id` does not exist, "
        "`422` if the file failed to process."
    ),
    responses={
        200: {"description": "Measurements retrieved successfully."},
        404: _404,
        422: {
            "description": "File processing previously failed; measurements are unavailable.",
            "content": {
                "application/json": {
                    "example": {"detail": "File processing failed; measurements unavailable."}
                }
            },
        },
    },
)
def get_file_measurements(
    file_id: str = _FILE_ID_PATH,
    db: Session = Depends(get_db),
):
    record = get_file_record(file_id, db)

    if record.status == "failed":
        raise HTTPException(
            status_code=422,
            detail="File processing failed; measurements unavailable.",
        )

    try:
        raw = get_measurements(record.file_path)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return MeasurementsResponse(
        file_id=file_id,
        measurements=[MeasurementItem.from_dict(m) for m in raw],
    )
