import re
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.models import FileRecord
from app.services.geo_processor import process_geodataframe

UPLOADS_DIR = Path("uploads")
ALLOWED_EXTENSIONS = {".kml", ".zip"}
SHAPEFILE_REQUIRED = {".shp", ".dbf", ".shx"}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
_SAFE_FILENAME_RE = re.compile(r"^[\w\-. ]+$")


def _validate_extension(filename: str) -> str:
    """Returns the lowercase extension or raises HTTP 400 for unsupported types."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )
    return ext


def _sanitize_filename(filename: str) -> str:
    """
    Rejects filenames that contain path separators or non-printable characters.
    Raises HTTP 400 if the filename is unsafe.
    """
    name = Path(filename).name  # strip any directory component
    if not name or not _SAFE_FILENAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    return name


def _safe_extract_zip(zip_path: Path, extract_to: Path) -> None:
    """
    Extracts a ZIP archive while blocking path traversal attacks.
    Raises HTTP 400 if any member path escapes the target directory.
    """
    extract_to_resolved = extract_to.resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            member_path = (extract_to / member).resolve()
            if not member_path.is_relative_to(extract_to_resolved):
                raise HTTPException(status_code=400, detail="ZIP contains unsafe paths.")
        zf.extractall(extract_to)


def _verify_shapefile(extract_dir: Path) -> None:
    """Raises HTTP 400 if the extracted directory is missing required Shapefile components."""
    extracted = {p.suffix.lower() for p in extract_dir.rglob("*") if p.is_file()}
    missing = SHAPEFILE_REQUIRED - extracted
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"ZIP is missing required Shapefile components: {sorted(missing)}",
        )


async def save_upload(file: UploadFile) -> tuple[str, str, str]:
    """
    Validates, saves, and extracts the uploaded file.

    Returns:
        (file_id, original_filename, saved_path_str)

    Raises:
        HTTP 400 for missing filename, empty file, oversized file,
        unsupported extension, unsafe filename, unsafe ZIP paths,
        or missing Shapefile components.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    safe_filename = _sanitize_filename(file.filename)
    ext = _validate_extension(safe_filename)
    contents = await file.read()

    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 100 MB limit.")

    file_id = str(uuid.uuid4())
    file_dir = UPLOADS_DIR / file_id
    file_dir.mkdir(parents=True, exist_ok=True)

    saved_path = file_dir / safe_filename
    saved_path.write_bytes(contents)

    if ext == ".zip":
        _safe_extract_zip(saved_path, file_dir)
        _verify_shapefile(file_dir)

    return file_id, safe_filename, str(saved_path)


def get_file_record(file_id: str, db: Session) -> FileRecord:
    """
    Fetches a FileRecord by ID.
    Raises HTTP 404 if not found.
    """
    record = db.get(FileRecord, file_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"File '{file_id}' not found.")
    return record


def process_file(record: FileRecord, db: Session) -> dict[str, Any]:
    """
    Runs geospatial processing on the saved file.
    Updates the DB record status to 'completed' or 'failed'.
    Returns the processing result dict.
    Raises HTTP 422 on processing failure.
    """
    try:
        result = process_geodataframe(record.file_path)
        record.feature_count = result["feature_count"]
        record.crs = result["crs"]
        record.status = "completed"
        db.commit()
        return result
    except ValueError as e:
        record.status = "failed"
        db.commit()
        raise HTTPException(status_code=422, detail=str(e))
