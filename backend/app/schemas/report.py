"""Pydantic schemas for report submission, import and responses."""
import uuid
from datetime import datetime, timezone
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


class ExtractedFacts(BaseModel):
    incident_category: str | None = None
    severity_cues: list[str] = Field(default_factory=list)
    urgency: str | None = None
    affected_persons: int | None = Field(default=None, ge=0)
    hazards: list[str] = Field(default_factory=list)
    requested_assistance: list[str] = Field(default_factory=list)
    location_mentions: list[str] = Field(default_factory=list)


class ExtractionReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    actor_id: uuid.UUID
    previous_facts: ExtractedFacts
    corrected_facts: ExtractedFacts
    created_at: datetime

    @field_validator("created_at", mode="before")
    @classmethod
    def _ensure_utc_created_at(cls, value):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class ExtractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    extractor_version: str
    extracted_facts: ExtractedFacts
    corrected_facts: ExtractedFacts | None
    effective_facts: ExtractedFacts
    confidence: dict[str, float]
    evidence: dict[str, list[str]]
    image_analysis_status: str
    image_cues: list[dict] | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    reviews: list[ExtractionReviewOut]

    @field_validator("reviewed_at", mode="before")
    @classmethod
    def _ensure_utc_reviewed_at(cls, value):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class ExtractionCorrection(BaseModel):
    facts: ExtractedFacts


class PriorityConfigInput(BaseModel):
    weights: dict[str, float]
    thresholds: dict[str, float]
    notes: str | None = Field(default=None, max_length=1000)


class PriorityConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: str
    is_active: bool
    weights: dict[str, float]
    thresholds: dict[str, float]
    notes: str | None
    created_by: uuid.UUID
    created_at: datetime


class PriorityOverrideInput(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    score: float | None = Field(default=None, ge=0, le=100)
    band: str | None = Field(default=None, pattern=r"^(LOW|MEDIUM|HIGH|CRITICAL)$")


class IncidentSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str


class ResponsePlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID
    version: int
    status: str
    source_facts: ExtractedFacts
    recommended_actions: list[str]
    resource_candidates: list[dict]
    gaps: list[str]
    human_approval_required: bool
    generated_by: uuid.UUID
    created_at: datetime
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_reason: str | None


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    report_id: uuid.UUID
    status: str
    confirmed_by: uuid.UUID
    confirmed_at: datetime
    plans: list[ResponsePlanOut]
    priority_score: float | None = None
    priority_band: str | None = None
    priority_rule_version: str | None = None
    priority_factors: dict[str, float] | None = None
    priority_is_overridden: bool = False
    priority_original_score: float | None = None
    priority_original_band: str | None = None
    priority_override_reason: str | None = None
    priority_override_by: uuid.UUID | None = None
    priority_override_at: datetime | None = None

    @field_validator("confirmed_at", "priority_override_at", mode="before")
    @classmethod
    def _ensure_utc_datetime(cls, value):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class PlanDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class ReportDismissal(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


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
    extraction: ExtractionOut | None = None
    incident: IncidentSummaryOut | None = None

    @field_validator("submitted_at", mode="before")
    @classmethod
    def _ensure_utc_timestamp(cls, value):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


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
