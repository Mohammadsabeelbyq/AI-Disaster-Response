"""Pydantic schemas for report submission, import and responses."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import DISASTER_TYPES


class ReportCreate(BaseModel):
    """Validated report data. Used by the web form, JSON import and CSV import alike."""
    model_config = ConfigDict(extra="ignore")

    disaster_type: str
    description: str = Field(min_length=1, max_length=5000)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    location_name: str | None = Field(default=None, max_length=255)

    @field_validator("disaster_type", mode="before")
    @classmethod
    def _normalise_type(cls, v):
        v = str(v or "").strip().upper().replace(" ", "_")
        if v not in DISASTER_TYPES:
            raise ValueError(f"must be one of: {', '.join(DISASTER_TYPES)}")
        return v

    @field_validator("description", mode="before")
    @classmethod
    def _strip_description(cls, v):
        if not isinstance(v, str):
            raise ValueError("description is required")
        return v.strip()

    @field_validator("location_name", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if isinstance(v, str):
            v = v.strip()
        return v or None


class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    file_name: str
    mime_type: str
    file_size_bytes: int
    media_type: str
    url: str


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    disaster_type: str
    description: str
    latitude: float
    longitude: float
    location_name: str | None
    status: str
    submitted_at: datetime
    image: MediaOut | None = None


class ImportRecordResult(BaseModel):
    record: int                                   # 1-based position (CSV: data row, header excluded)
    status: Literal["accepted", "rejected"]
    reportId: uuid.UUID | None = None
    errors: list[str] | None = None


class ImportSummary(BaseModel):
    total: int
    accepted: int
    rejected: int
    results: list[ImportRecordResult]
