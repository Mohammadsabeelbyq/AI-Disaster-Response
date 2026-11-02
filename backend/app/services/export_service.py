"""Incident data export service for ADM-44.

Provides filtered CSV and JSON incident exports with data sanitization.
"""
import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.incident import Incident
from app.models.report import IncidentReport
from app.services.errors import ValidationFailed


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    try:
        # Support both '2026-11-01' and '2026-11-01T12:00:00' formats
        clean = value.strip()
        if len(clean) == 10:
            return datetime.fromisoformat(clean).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(clean)
    except Exception as exc:
        raise ValidationFailed(f"Invalid date format '{value}'. Use ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS).") from exc


def query_export_incidents(
    db: Session,
    *,
    status: str | None = None,
    priority: str | None = None,
    disaster_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    search: str | None = None,
) -> list[Incident]:
    """Query incidents based on filters, eager-loading related report, extraction, and plans."""
    stmt = (
        select(Incident)
        .join(Incident.report)
        .options(
            joinedload(Incident.report).joinedload(IncidentReport.extraction),
            joinedload(Incident.report).joinedload(IncidentReport.location_correction),
            joinedload(Incident.plans),
        )
        .order_by(Incident.confirmed_at.desc())
    )

    if status and status.strip():
        stmt = stmt.where(Incident.status == status.strip().upper())

    if priority and priority.strip():
        stmt = stmt.where(Incident.priority_band == priority.strip().upper())

    if disaster_type and disaster_type.strip():
        stmt = stmt.where(IncidentReport.disaster_type == disaster_type.strip().upper())

    start_dt = _parse_iso_datetime(start_date)
    if start_dt:
        stmt = stmt.where(Incident.confirmed_at >= start_dt)

    end_dt = _parse_iso_datetime(end_date)
    if end_dt:
        stmt = stmt.where(Incident.confirmed_at <= end_dt)

    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            IncidentReport.description.ilike(term) | IncidentReport.location_name.ilike(term)
        )

    return list(db.scalars(stmt).unique().all())


def serialize_incident_record(incident: Incident) -> dict[str, Any]:
    """Map an incident record to a safe, sanitized dictionary for export."""
    report = incident.report
    extraction = report.extraction if report else None
    facts = extraction.extracted_facts if extraction and extraction.extracted_facts else {}

    # Calculate active assignments across all plans
    active_assignments_count = 0
    if incident.plans:
        for p in incident.plans:
            if hasattr(p, "assignments") and p.assignments:
                active_assignments_count += sum(1 for a in p.assignments if getattr(a, "is_active", False))

    lat = report.map_latitude if report else None
    lng = report.map_longitude if report else None
    loc_name = (report.map_location_name or report.location_name or "") if report else ""

    return {
        "incident_id": str(incident.id),
        "status": incident.status,
        "disaster_type": report.disaster_type if report else "",
        "priority_band": incident.priority_band or "UNRATED",
        "priority_score": round(float(incident.priority_score), 2) if incident.priority_score is not None else None,
        "priority_is_overridden": bool(incident.priority_is_overridden),
        "priority_override_reason": incident.priority_override_reason or "",
        "location_name": loc_name,
        "latitude": float(lat) if lat is not None else None,
        "longitude": float(lng) if lng is not None else None,
        "reported_at": report.submitted_at.isoformat() if report and report.submitted_at else "",
        "confirmed_at": incident.confirmed_at.isoformat() if incident.confirmed_at else "",
        "description": report.description if report else "",
        "urgency": facts.get("urgency", ""),
        "casualties": facts.get("casualties", None),
        "hazards": ", ".join(facts.get("hazards", [])) if isinstance(facts.get("hazards"), list) else str(facts.get("hazards", "")),
        "damage_severity": facts.get("damage_severity", ""),
        "requested_assistance": ", ".join(facts.get("requested_assistance", [])) if isinstance(facts.get("requested_assistance"), list) else str(facts.get("requested_assistance", "")),
        "response_plans_count": len(incident.plans) if incident.plans else 0,
        "active_assignments_count": active_assignments_count,
    }


def export_incidents_as_json(records: list[dict[str, Any]]) -> str:
    """Format records as a formatted JSON array string."""
    return json.dumps(records, indent=2, default=str)


def export_incidents_as_csv(records: list[dict[str, Any]]) -> str:
    """Format records as a RFC 4180 compliant CSV string."""
    fieldnames = [
        "incident_id",
        "status",
        "disaster_type",
        "priority_band",
        "priority_score",
        "priority_is_overridden",
        "priority_override_reason",
        "location_name",
        "latitude",
        "longitude",
        "reported_at",
        "confirmed_at",
        "description",
        "urgency",
        "casualties",
        "hazards",
        "damage_severity",
        "requested_assistance",
        "response_plans_count",
        "active_assignments_count",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in records:
        writer.writerow(row)
    return output.getvalue()
