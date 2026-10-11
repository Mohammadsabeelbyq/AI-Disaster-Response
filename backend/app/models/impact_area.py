"""Coordinator-defined impact areas stored as radius values or GeoJSON."""
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base

if TYPE_CHECKING:
    from app.models.incident import Incident


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ImpactArea(Base):
    __tablename__ = "incident_impact_areas"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="CASCADE"), unique=True, nullable=False)
    geometry_type: Mapped[str] = mapped_column(String(20), nullable=False)
    radius_m: Mapped[float | None] = mapped_column(Float)
    polygon: Mapped[dict | None] = mapped_column(JSON)
    updated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now,
                                                 onupdate=_now, nullable=False)

    incident: Mapped["Incident"] = relationship(back_populates="impact_area")
