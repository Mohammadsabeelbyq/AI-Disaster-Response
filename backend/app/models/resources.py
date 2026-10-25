"""Department master data, registered response resources, and availability history."""
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, Numeric, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base

if TYPE_CHECKING:
    from app.models.incident import ResponsePlan


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    department_type: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    resources: Mapped[list["Resource"]] = relationship(back_populates="department")


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6, asdecimal=False))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6, asdecimal=False))
    availability: Mapped[str] = mapped_column(String(20), nullable=False, default="AVAILABLE")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    department: Mapped[Department] = relationship(back_populates="resources")
    availability_events: Mapped[list["ResourceAvailabilityEvent"]] = relationship(
        back_populates="resource", cascade="all, delete-orphan",
        order_by="ResourceAvailabilityEvent.changed_at")
    assignments: Mapped[list["ResourceAssignment"]] = relationship(back_populates="resource")


class ResourceAvailabilityEvent(Base):
    __tablename__ = "resource_availability_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
    changed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    previous_availability: Mapped[str | None] = mapped_column(String(20))
    new_availability: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    resource: Mapped[Resource] = relationship(back_populates="availability_events")


class ResourceAssignment(Base):
    __tablename__ = "resource_assignments"
    __table_args__ = (
        Index(
            "uq_resource_assignments_active_resource",
            "resource_id",
            unique=True,
            sqlite_where=text("released_at IS NULL"),
            postgresql_where=text("released_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("resources.id", ondelete="RESTRICT"), nullable=False, index=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False, index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("response_plans.id", ondelete="RESTRICT"), nullable=False, index=True)
    assigned_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    released_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_reason: Mapped[str | None] = mapped_column(String(1000))

    resource: Mapped[Resource] = relationship(back_populates="assignments")
    plan: Mapped["ResponsePlan"] = relationship(back_populates="assignments")

    @property
    def is_active(self) -> bool:
        return self.released_at is None
