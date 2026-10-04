"""Structured, evidence-linked analysis kept separate from submitted report content."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReportExtraction(Base):
    __tablename__ = "report_extractions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incident_reports.id", ondelete="CASCADE"), unique=True, nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(40), nullable=False)
    extracted_facts: Mapped[dict] = mapped_column(JSON, nullable=False)
    confidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    image_analysis_status: Mapped[str] = mapped_column(String(30), nullable=False)
    image_cues: Mapped[list | None] = mapped_column(JSON)
    corrected_facts: Mapped[dict | None] = mapped_column(JSON)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    report: Mapped["IncidentReport"] = relationship(back_populates="extraction")
    reviews: Mapped[list["ExtractionReview"]] = relationship(
        back_populates="extraction", cascade="all, delete-orphan", order_by="ExtractionReview.created_at")

    @property
    def effective_facts(self) -> dict:
        """Facts downstream workflows should consume after coordinator review."""
        return self.corrected_facts or self.extracted_facts


class ExtractionReview(Base):
    __tablename__ = "extraction_reviews"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    extraction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("report_extractions.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    previous_facts: Mapped[dict] = mapped_column(JSON, nullable=False)
    corrected_facts: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    extraction: Mapped[ReportExtraction] = relationship(back_populates="reviews")