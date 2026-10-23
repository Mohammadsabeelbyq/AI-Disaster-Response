"""Human-reviewed links between reports; relationships never merge reports."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReportRelationship:
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class ReportRelationshipRecord(Base):
    __tablename__ = "report_relationships"
    __table_args__ = (
        UniqueConstraint("report_id", "related_report_id", name="uq_report_relationship_pair"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incident_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    related_report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incident_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default=ReportRelationship.PROPOSED, nullable=False, index=True)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    proposed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
