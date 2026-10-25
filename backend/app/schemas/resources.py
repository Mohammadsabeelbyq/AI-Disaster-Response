"""Validation and response schemas for department and resource management."""
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


DEPARTMENT_TYPES = ("FIRE", "MEDICAL", "POLICE", "DISASTER_MANAGEMENT")
RESOURCE_TYPES = ("RESCUE_TEAM", "VEHICLE", "SHELTER", "SUPPLY")
RESOURCE_AVAILABILITY = ("AVAILABLE", "UNAVAILABLE", "MAINTENANCE")


def _normalise_code(value: object) -> str:
    return str(value or "").strip().upper().replace(" ", "_")


class DepartmentCreate(BaseModel):
    code: str = Field(min_length=2, max_length=30, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=150)
    department_type: Literal["FIRE", "MEDICAL", "POLICE", "DISASTER_MANAGEMENT"]

    @field_validator("code", mode="before")
    @classmethod
    def _normalise_code(cls, value):
        return _normalise_code(value)

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    department_type: Literal["FIRE", "MEDICAL", "POLICE", "DISASTER_MANAGEMENT"] | None = None
    is_active: bool | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    department_type: str
    is_active: bool
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ResourceCreate(BaseModel):
    code: str = Field(min_length=2, max_length=30, pattern=r"^[A-Za-z0-9_-]+$")
    department_id: uuid.UUID
    resource_type: Literal["RESCUE_TEAM", "VEHICLE", "SHELTER", "SUPPLY"]
    name: str = Field(min_length=1, max_length=150)
    capabilities: list[str] = Field(min_length=1, max_length=30)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    availability: Literal["AVAILABLE", "UNAVAILABLE", "MAINTENANCE"] = "AVAILABLE"

    @field_validator("code", mode="before")
    @classmethod
    def _normalise_code(cls, value):
        return _normalise_code(value)

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("capabilities", mode="before")
    @classmethod
    def _normalise_capabilities(cls, value):
        if not isinstance(value, list):
            return value
        normalized = [_normalise_code(item) for item in value]
        if any(not item for item in normalized):
            raise ValueError("Capabilities cannot be empty.")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Capabilities must be unique.")
        return normalized


class ResourceUpdate(BaseModel):
    department_id: uuid.UUID | None = None
    resource_type: Literal["RESCUE_TEAM", "VEHICLE", "SHELTER", "SUPPLY"] | None = None
    name: str | None = Field(default=None, min_length=1, max_length=150)
    capabilities: list[str] | None = Field(default=None, min_length=1, max_length=30)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("capabilities", mode="before")
    @classmethod
    def _normalise_capabilities(cls, value):
        if value is None or not isinstance(value, list):
            return value
        normalized = [_normalise_code(item) for item in value]
        if any(not item for item in normalized):
            raise ValueError("Capabilities cannot be empty.")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Capabilities must be unique.")
        return normalized


class ResourceAvailabilityUpdate(BaseModel):
    availability: Literal["AVAILABLE", "UNAVAILABLE", "MAINTENANCE"]
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def _trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class ResourceAvailabilityEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resource_id: uuid.UUID
    changed_by: uuid.UUID
    previous_availability: str | None
    new_availability: str
    reason: str
    changed_at: datetime

    @field_validator("changed_at", mode="before")
    @classmethod
    def _ensure_utc(cls, value):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    department_id: uuid.UUID
    department: DepartmentOut
    resource_type: str
    name: str
    capabilities: list[str]
    latitude: float
    longitude: float
    availability: str
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    availability_events: list[ResourceAvailabilityEventOut]


class ResourceCandidateOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    resource_type: str
    department_code: str
    department_name: str
    matched_capabilities: list[str]
