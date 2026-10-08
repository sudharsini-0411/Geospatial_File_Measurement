"""
API endpoint tests.

Covers:
  - GET /
  - POST /api/files/  (KML, ZIP Shapefile, invalid extension, empty file,
                       oversized file, ZIP path traversal, incomplete ZIP)
  - GET /api/files/{id}/
  - GET /api/files/{id}/measurements/
  - 404 for unknown file ID
  - 422 for a file whose processing failed
"""

import io
import zipfile
from unittest.mock import patch

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# 1. GET /
# ---------------------------------------------------------------------------

def test_root(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Geospatial Measurement API is running"}


# ---------------------------------------------------------------------------
# 2. POST /api/files/ — KML upload
# ---------------------------------------------------------------------------

def test_upload_kml(client: TestClient, kml_file, mock_process_geodataframe) -> None:
    filename, content, content_type = kml_file
    response = client.post(
        "/api/files/",
        files={"file": (filename, content, content_type)},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["filename"] == filename
    assert data["status"] == "completed"
    assert data["feature_count"] >= 1
    assert isinstance(data["features"], list)


# ---------------------------------------------------------------------------
# 3. POST /api/files/ — ZIP Shapefile upload
# ---------------------------------------------------------------------------

def test_upload_zip_shapefile(client: TestClient, zip_shapefile, mock_process_geodataframe) -> None:
    filename, content, content_type = zip_shapefile
    response = client.post(
        "/api/files/",
        files={"file": (filename, content, content_type)},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["filename"] == filename
    assert data["status"] == "completed"
    assert data["feature_count"] >= 1


# ---------------------------------------------------------------------------
# 4. POST /api/files/ — invalid file extension
# ---------------------------------------------------------------------------

def test_upload_invalid_extension(client: TestClient, invalid_file) -> None:
    filename, content, content_type = invalid_file
    response = client.post(
        "/api/files/",
        files={"file": (filename, content, content_type)},
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 5. POST /api/files/ — empty file
# ---------------------------------------------------------------------------

def test_upload_empty_file(client: TestClient, empty_file) -> None:
    filename, content, content_type = empty_file
    response = client.post(
        "/api/files/",
        files={"file": (filename, content, content_type)},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 6. GET /api/files/{id}/ — file information endpoint
# ---------------------------------------------------------------------------

def test_get_file_info(client: TestClient, kml_file, mock_process_geodataframe) -> None:
    filename, content, content_type = kml_file
    upload = client.post(
        "/api/files/",
        files={"file": (filename, content, content_type)},
    )
    assert upload.status_code == 201
    file_id = upload.json()["id"]

    response = client.get(f"/api/files/{file_id}/")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == file_id
    assert data["filename"] == filename
    assert data["status"] == "completed"
    assert "file_path" not in data
    assert "created_at" in data


# ---------------------------------------------------------------------------
# 7. GET /api/files/{id}/ — missing file ID returns 404
# ---------------------------------------------------------------------------

def test_get_file_not_found(client: TestClient) -> None:
    response = client.get("/api/files/nonexistent-id-12345/")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 8. GET /api/files/{id}/measurements/ — measurements endpoint
# ---------------------------------------------------------------------------

def test_get_measurements(client: TestClient, kml_file, mock_process_geodataframe) -> None:
    filename, content, content_type = kml_file
    upload = client.post(
        "/api/files/",
        files={"file": (filename, content, content_type)},
    )
    assert upload.status_code == 201
    file_id = upload.json()["id"]

    response = client.get(f"/api/files/{file_id}/measurements/")
    assert response.status_code == 200
    data = response.json()
    assert data["file_id"] == file_id
    assert isinstance(data["measurements"], list)
    assert len(data["measurements"]) >= 1


# ---------------------------------------------------------------------------
# 9. GET /api/files/{id}/measurements/ — missing file ID returns 404
# ---------------------------------------------------------------------------

def test_get_measurements_not_found(client: TestClient) -> None:
    response = client.get("/api/files/nonexistent-id-99999/measurements/")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 10. Upload response must not expose file_path
# ---------------------------------------------------------------------------

def test_upload_response_no_file_path(client: TestClient, kml_file, mock_process_geodataframe) -> None:
    filename, content, content_type = kml_file
    response = client.post(
        "/api/files/",
        files={"file": (filename, content, content_type)},
    )
    assert response.status_code == 201
    assert "file_path" not in response.json()


# ---------------------------------------------------------------------------
# 11. File size limit
# ---------------------------------------------------------------------------

def test_upload_oversized_file(client: TestClient) -> None:
    oversized = b"x" * (100 * 1024 * 1024 + 1)
    response = client.post(
        "/api/files/",
        files={"file": ("big.kml", oversized, "application/vnd.google-earth.kml+xml")},
    )
    assert response.status_code == 400
    assert "100 MB" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 12. ZIP path-traversal rejection
# ---------------------------------------------------------------------------

def test_upload_zip_path_traversal(client: TestClient) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.shp", b"fake")
    response = client.post(
        "/api/files/",
        files={"file": ("traversal.zip", buf.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    assert "unsafe" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 13. ZIP missing required Shapefile components
# ---------------------------------------------------------------------------

def test_upload_zip_missing_shapefile_components(client: TestClient) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.shp", b"fake")  # missing .dbf and .shx
    response = client.post(
        "/api/files/",
        files={"file": ("incomplete.zip", buf.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    assert "missing" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 14. Measurements endpoint returns 422 for a file whose processing failed
# ---------------------------------------------------------------------------

def test_get_measurements_failed_file(client: TestClient, kml_file) -> None:
    filename, content, content_type = kml_file

    with patch(
        "app.services.file_processor.process_geodataframe",
        side_effect=ValueError("corrupt file"),
    ):
        upload = client.post(
            "/api/files/",
            files={"file": (filename, content, content_type)},
        )
    assert upload.status_code == 422

    # The DB record was written with status=failed before the 422 was raised.
    # Re-upload with the mock restored to get a valid id, then manually set
    # status to failed and confirm the measurements endpoint returns 422.
    with patch("app.services.file_processor.process_geodataframe") as mock_proc, \
         patch("app.routers.files.get_measurements"):
        mock_proc.return_value = {
            "feature_count": 1,
            "crs": "EPSG:4326",
            "features": [],
        }
        upload2 = client.post(
            "/api/files/",
            files={"file": (filename, content, content_type)},
        )
    assert upload2.status_code == 201
    file_id = upload2.json()["id"]

    # Directly update the record status to simulate a previously failed upload
    from tests.conftest import TestingSessionLocal
    from app.models import FileRecord
    db = TestingSessionLocal()
    try:
        record = db.get(FileRecord, file_id)
        record.status = "failed"
        db.commit()
    finally:
        db.close()

    response = client.get(f"/api/files/{file_id}/measurements/")
    assert response.status_code == 422
    assert "failed" in response.json()["detail"].lower()
