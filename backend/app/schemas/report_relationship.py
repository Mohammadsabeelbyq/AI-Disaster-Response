"""API schemas for potential report relationships and coordinator decisions."""
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RelationshipReportOut(BaseModel):
    id: uuid.UUID
    disaster_type: str
    description: str
    latitude: float
    longitude: float
    location_name: str | None
    status: str
    submitted_at: datetime

    @field_validator("submitted_at", mode="before")
    @classmethod
    def _ensure_utc_timestamp(cls, value):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class ReportRelationshipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    report: RelationshipReportOut
    related_report: RelationshipReportOut
    status: Literal["PROPOSED", "CONFIRMED", "REJECTED"]
    evidence: dict[str, float | bool | None]
    proposed_by: uuid.UUID
    proposed_at: datetime
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_reason: str | None

    @field_validator("proposed_at", "decided_at", mode="before")
    @classmethod
    def _ensure_utc_timestamps(cls, value):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class RelationshipDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)
