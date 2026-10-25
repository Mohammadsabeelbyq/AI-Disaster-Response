"""Validation and response schemas for department and resource management."""
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DEPARTMENT_TYPES = ("FIRE", "MEDICAL", "POLICE", "DISASTER_MANAGEMENT")
RESOURCE_TYPES = ("RESCUE_TEAM", "VEHICLE", "SHELTER", "SUPPLY")
RESOURCE_AVAILABILITY = (
    "AVAILABLE", "BUSY", "DEPLOYED", "UNAVAILABLE", "ASSIGNED", "INACTIVE", "MAINTENANCE",
)


def _normalise_code(value: object) -> str:
    return str(value or "").strip().upper().replace(" ", "_")


class DepartmentCreate(BaseModel):
    code: str = Field(min_length=2, max_length=30, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=150)
    department_type: Literal["FIRE", "MEDICAL", "POLICE", "DISASTER_MANAGEMENT"]

    @field_validator("code", mode="before")
    @classmethod
    def _normalise_code(cls, value):
        code = _normalise_code(value)
        if code == "LEGACY_UNASSIGNED":
            raise ValueError("This department code is reserved for migrated resources.")
        return code

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
    availability: Literal[
        "AVAILABLE", "BUSY", "DEPLOYED", "UNAVAILABLE", "ASSIGNED", "INACTIVE", "MAINTENANCE",
    ] = "AVAILABLE"

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
        return list(dict.fromkeys(normalized))


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
        return list(dict.fromkeys(normalized))

    @model_validator(mode="after")
    def coordinates_are_updated_as_a_pair(self):
        if ("latitude" in self.model_fields_set) != ("longitude" in self.model_fields_set):
            raise ValueError("latitude and longitude must be updated together")
        return self


class ResourceAvailabilityUpdate(BaseModel):
    availability: Literal[
        "AVAILABLE", "BUSY", "DEPLOYED", "UNAVAILABLE", "INACTIVE", "MAINTENANCE",
    ]
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def _trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class ResourceBulkAvailabilityInput(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def _trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class ResourceAvailabilitySkipped(BaseModel):
    resource_id: uuid.UUID
    code: str
    reason: str


class ResourceBulkAvailabilityOut(BaseModel):
    resources_made_available: int
    already_available_count: int
    released_assignment_count: int
    skipped: list[ResourceAvailabilitySkipped]


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


class ResourceAssignmentInput(BaseModel):
    resource_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def _trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class ResourceAssignmentReleaseInput(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def _trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class ResourceAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resource_id: uuid.UUID
    incident_id: uuid.UUID
    plan_id: uuid.UUID
    assigned_by: uuid.UUID
    assigned_at: datetime
    reason: str
    released_by: uuid.UUID | None
    released_at: datetime | None
    release_reason: str | None
    is_active: bool

    @field_validator("assigned_at", "released_at", mode="before")
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
    resource_type: str | None
    name: str
    capabilities: list[str]
    latitude: float | None
    longitude: float | None
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


class NearbyResourceOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    resource_type: str | None
    department_id: uuid.UUID
    department_name: str
    latitude: float
    longitude: float
    capabilities: list[str]
    availability: str
    distance_m: int


class NearbyResourcesOut(BaseModel):
    incident_id: uuid.UUID
    radius_m: int
    requested_capabilities: list[str]
    resources: list[NearbyResourceOut]
