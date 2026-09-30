"""HTTP layer for incident report submission. Thin: parse the request, call a service."""
import uuid

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.config import get_settings
from app.database import get_db
from app.schemas.report import ImportSummary, ReportCreate, ReportOut
from app.services import import_service, media_service, report_service
from app.services.errors import ImageRejected, NotFound, ValidationFailed

router = APIRouter(prefix="/reports", tags=["reports"])


async def _read_upload(upload: UploadFile | None) -> media_service.ValidatedImage | None:
    """Return a validated image, or None when the optional image was not provided."""
    if upload is None or (not upload.filename and upload.size in (0, None)):
        return None  # browsers send an empty file part when no file was chosen
    limit = get_settings().max_image_bytes
    data = await upload.read(limit + 1)  # never read more than limit+1 bytes
    return media_service.validate_image(upload.filename, upload.content_type, data)


@router.post("", response_model=ReportOut, status_code=201)
async def submit_report(
    disaster_type: str | None = Form(None),
    description: str | None = Form(None),
    latitude: str | None = Form(None),
    longitude: str | None = Form(None),
    location_name: str | None = Form(None),
    image: UploadFile | None = None,
    db: Session = Depends(get_db),
    user_id: uuid.UUID | None = Depends(get_current_user_id),
):
    """Web-form submission (multipart/form-data). `image` is optional."""
    raw = {"disaster_type": disaster_type, "description": description, "latitude": latitude,
           "longitude": longitude, "location_name": location_name}
    try:
        data = ReportCreate.model_validate({k: v for k, v in raw.items() if v not in (None, "")})
    except ValidationError as exc:
        raise ValidationFailed("Invalid report.", import_service.format_validation_errors(exc)) from exc
    validated_image = await _read_upload(image)  # invalid image => whole submission rejected
    return report_service.create_report(db, data, validated_image, submitted_by=user_id)


@router.post("/import/json", response_model=ImportSummary)
async def import_json(request: Request, db: Session = Depends(get_db)):
    """Body: JSON array of reports (or one object, or {"reports": [...]})."""
    return import_service.import_json(db, await request.body())


@router.post("/import/csv", response_model=ImportSummary)
async def import_csv(request: Request, db: Session = Depends(get_db)):
    """Body: raw CSV text with header row (Content-Type: text/csv)."""
    return import_service.import_csv(db, await request.body())


@router.get("", response_model=list[ReportOut])
def list_reports(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return report_service.list_reports(db, min(max(limit, 1), 200), max(offset, 0))


@router.get("/{report_id}", response_model=ReportOut)
def get_report(report_id: uuid.UUID, db: Session = Depends(get_db)):
    return report_service.get_report(db, report_id)


@router.post("/{report_id}/media", response_model=ReportOut, status_code=201)
async def attach_media(report_id: uuid.UUID, image: UploadFile, db: Session = Depends(get_db)):
    """Attach an image to an already-created report."""
    validated = await _read_upload(image)
    if validated is None:
        raise ImageRejected("No image file was provided.", 422)
    return report_service.attach_image(db, report_id, validated)


@router.get("/{report_id}/image")
def get_report_image(report_id: uuid.UUID, db: Session = Depends(get_db)):
    report = report_service.get_report(db, report_id)
    if report.image is None:
        raise NotFound("This report has no image.")
    path = media_service.absolute_path(report.image.storage_path)
    if not path.exists():
        raise NotFound("Image file is missing.")
    return FileResponse(path, media_type=report.image.mime_type)
