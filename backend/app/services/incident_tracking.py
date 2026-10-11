"""Incident-tracking metadata utilities.

This module holds the team-owned contract for story 1.4: every accepted report must
carry a unique identifier and a timestamp that persists after submission.

Other team members should extend this service for incident metadata, audit state, and
tracking-related rules rather than creating ad hoc generation logic in unrelated files.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.report import IncidentReport


def generate_incident_id() -> uuid.UUID:
    """Return a fresh unique identifier for an accepted report."""
    return uuid.uuid4()


def utc_now() -> datetime:
    """Return the current UTC timestamp used for submission metadata."""
    return datetime.now(timezone.utc)


def ensure_report_tracking_metadata(report: "IncidentReport") -> "IncidentReport":
    """Ensure the report carries the required submission metadata.

    This is the authoritative boundary for Story 1.4 and is intentionally kept separate
    from report creation logic so other team members can add downstream workflow logic
    without changing the same class or service in multiple places.
    """
    if report.id is None:
        report.id = generate_incident_id()
    if report.submitted_at is None:
        report.submitted_at = utc_now()
    return report
