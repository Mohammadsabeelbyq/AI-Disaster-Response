"""Pydantic schemas for coordinator notifications."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recipient_id: uuid.UUID
    incident_id: uuid.UUID | None = None
    response_plan_id: uuid.UUID | None = None
    assignment_id: uuid.UUID | None = None
    notification_type: str
    title: str
    message: str
    is_read: bool
    dedupe_key: str | None = None
    created_at: datetime


class UnreadCountOut(BaseModel):
    unread_count: int


class MarkReadOut(BaseModel):
    updated_count: int
