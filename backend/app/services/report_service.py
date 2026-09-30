"""INCIDENT (REPORT) SERVICE - the only place that creates/reads reports.
The web form, the media endpoint and both importers all go through create_report()."""
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import IncidentMedia, IncidentReport, ReportStatus
from app.schemas.report import ReportCreate
from app.services import media_service
from app.services.errors import Conflict, NotFound, StorageFailure
from app.services.media_service import ValidatedImage

log = logging.getLogger(__name__)


def _media_row(image: ValidatedImage, storage_path: str) -> IncidentMedia:
    return IncidentMedia(
        file_name=image.original_name, mime_type=image.mime_type,
        file_size_bytes=len(image.data), file_hash=image.file_hash,
        storage_path=storage_path, media_type="IMAGE", processing_status="PENDING")


def create_report(db: Session, data: ReportCreate, image: ValidatedImage | None = None,
                  submitted_by: uuid.UUID | None = None) -> IncidentReport:
    """Create ONE report (+ its optional, already-validated image) in a single transaction.
    If anything fails nothing is left behind: no report row and no orphan file."""
    report = IncidentReport(
        submitted_by=submitted_by, status=ReportStatus.SUBMITTED, **data.model_dump())
    stored_path = None
    try:
        if image is not None:
            stored_path = media_service.store_image(image)
            report.media.append(_media_row(image, stored_path))
        db.add(report)
        db.commit()
    except (SQLAlchemyError, OSError) as exc:
        db.rollback()
        if stored_path:
            media_service.delete_image(stored_path)
        log.exception("Failed to store report")
        raise StorageFailure("The report could not be saved. Please try again.") from exc
    return report


def attach_image(db: Session, report_id: uuid.UUID, image: ValidatedImage) -> IncidentReport:
    """Attach an image to an existing report (one image per report for now)."""
    report = get_report(db, report_id)
    if report.media:
        raise Conflict("This report already has an image.")
    stored_path = None
    try:
        stored_path = media_service.store_image(image)
        report.media.append(_media_row(image, stored_path))
        db.commit()
    except (SQLAlchemyError, OSError) as exc:
        db.rollback()
        if stored_path:
            media_service.delete_image(stored_path)
        log.exception("Failed to attach image")
        raise StorageFailure("The image could not be saved. Please try again.") from exc
    return report


def get_report(db: Session, report_id: uuid.UUID) -> IncidentReport:
    report = db.get(IncidentReport, report_id)
    if report is None:
        raise NotFound("Report not found.")
    return report


def list_reports(db: Session, limit: int = 50, offset: int = 0) -> list[IncidentReport]:
    stmt = (select(IncidentReport).order_by(IncidentReport.submitted_at.desc())
            .limit(limit).offset(offset))
    return list(db.scalars(stmt))
