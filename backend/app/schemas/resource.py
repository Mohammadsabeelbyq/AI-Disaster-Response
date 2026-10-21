"""Schemas for registering operational resources and returning proximity results."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

ResourceStatus = Literal["AVAILABLE", "BUSY", "DEPLOYED", "UNAVAILABLE", "ASSIGNED", "INACTIVE"]


class ResourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    resource_type: str | None = Field(default=None, max_length=50, validation_alias=AliasChoices("resource_type", "type"))
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    capabilities: list[str] = Field(default_factory=list, max_length=30)
    status: ResourceStatus = "AVAILABLE"

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("capabilities")
    @classmethod
    def normalize_capabilities(cls, values):
        normalized = []
        for value in values:
            capability = value.strip().upper().replace(" ", "_")
            if not capability or len(capability) > 50 or not all(
                char.isascii() and (char.isalnum() or char in "_-") for char in capability
            ):
                raise ValueError("capabilities must be short words containing letters, digits, _ or -")
            if capability not in normalized:
                normalized.append(capability)
        return normalized

    @model_validator(mode="after")
    def coordinates_are_a_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must either both be set or both be omitted")
        return self


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    resource_type: str | None = None
    type: str | None = None
    latitude: float | None
    longitude: float | None
    capabilities: list[str]
    status: ResourceStatus
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class NearbyResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    resource_type: str | None = None
    type: str | None = None
    latitude: float
    longitude: float
    capabilities: list[str]
    status: ResourceStatus
    distance_m: int


class NearbyResourcesOut(BaseModel):
    incident_id: uuid.UUID
    radius_m: int
    requested_capabilities: list[str]
    resources: list[NearbyResourceOut]
