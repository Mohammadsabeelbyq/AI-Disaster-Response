"""Tables from the Database Design doc: incident_reports + incident_media (subset of columns
needed for report submission). Add the remaining columns/FKs (reviewed_by, incident_id...) later."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.services.incident_tracking import generate_incident_id, utc_now


class ReportStatus:
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    DISMISSED = "DISMISSED"


class IncidentReport(Base):
    __tablename__ = "incident_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=generate_incident_id)
    # Add the users.id foreign key alongside the project's Alembic migration setup.
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    disaster_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    latitude: Mapped[float] = mapped_column(Numeric(9, 6, asdecimal=False), nullable=False)
    longitude: Mapped[float] = mapped_column(Numeric(9, 6, asdecimal=False), nullable=False)
    location_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default=ReportStatus.SUBMITTED, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    media: Mapped[list["IncidentMedia"]] = relationship(
        back_populates="report", cascade="all, delete-orphan")
    extraction: Mapped["ReportExtraction | None"] = relationship(
        back_populates="report", cascade="all, delete-orphan", uselist=False)
    incident: Mapped["Incident | None"] = relationship(
        back_populates="report", cascade="all, delete-orphan", uselist=False)

    @property
    def image(self) -> "IncidentMedia | None":
        """The report's (single) image, if any. Used by the ReportOut schema."""
        return self.media[0] if self.media else None

    @property
    def searchable_text(self) -> str:
        """Text a FAISS embedding should be built from (see app/faiss_search)."""
        parts = [self.disaster_type, self.location_name or "", self.description]
        return ". ".join(p for p in parts if p)


class IncidentMedia(Base):
    __tablename__ = "incident_media"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incident_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)   # original name (display only)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)  # sha256
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)       # relative to UPLOAD_DIR
    media_type: Mapped[str] = mapped_column(String(10), default="IMAGE", nullable=False)
    processing_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    report: Mapped[IncidentReport] = relationship(back_populates="media")

    @property
    def url(self) -> str:
        return f"/reports/{self.report_id}/image"



