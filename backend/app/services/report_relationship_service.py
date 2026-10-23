"""Detection and coordinator decisions for possible report relationships."""
import logging
import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import IncidentReport, ReportRelationshipRecord
from app.models.incident import WorkflowAudit
from app.schemas.report_relationship import RelationshipReportOut
from app.services.errors import Conflict, NotFound, ServiceUnavailable
from app.services.incident_tracking import utc_now

log = logging.getLogger(__name__)


def _pair_ids(first: uuid.UUID, second: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    return tuple(sorted((first, second), key=str))


def _hours_between(first: datetime, second: datetime) -> float:
    if first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)
    if second.tzinfo is None:
        second = second.replace(tzinfo=timezone.utc)
    return abs((first - second).total_seconds()) / 3600


def _distance_km(first: IncidentReport, second: IncidentReport) -> float:
    lat1, lat2 = math.radians(float(first.map_latitude)), math.radians(float(second.map_latitude))
    delta_lat = lat2 - lat1
    delta_lon = math.radians(float(second.map_longitude) - float(first.map_longitude))
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, haversine)))


def _semantic_scores(source: IncidentReport, candidates: list[IncidentReport]) -> list[float]:
    try:
        from app.faiss_search.embeddings import embed_texts
    except ImportError as exc:
        log.exception("Semantic report matching dependencies are unavailable")
        raise ServiceUnavailable(
            "Semantic report matching is enabled, but its optional dependencies are unavailable."
        ) from exc

    try:
        vectors = embed_texts([source.searchable_text, *(item.searchable_text for item in candidates)])
    except ImportError as exc:
        log.exception("Semantic report matching dependencies are unavailable")
        raise ServiceUnavailable(
            "Semantic report matching is enabled, but its optional dependencies are unavailable."
        ) from exc
    return [float(score) for score in vectors[1:] @ vectors[0]]


def detect_potential_relationships(
    db: Session, report_id: uuid.UUID, actor_id: uuid.UUID
) -> list[ReportRelationshipRecord]:
    source = db.get(IncidentReport, report_id)
    if source is None:
        raise NotFound("Report not found.")
    if source.status == "DISMISSED":
        raise Conflict("Dismissed reports cannot be used to propose relationships.")

    settings = get_settings()
    reports = db.scalars(
        select(IncidentReport).where(
            IncidentReport.id != source.id,
            IncidentReport.status != "DISMISSED",
        )
    ).all()
    candidates: list[tuple[IncidentReport, float, float]] = []
    for candidate in reports:
        hours = _hours_between(source.submitted_at, candidate.submitted_at)
        if hours > settings.report_relationship_time_window_hours:
            continue
        distance = _distance_km(source, candidate)
        if distance <= settings.report_relationship_radius_km:
            candidates.append((candidate, hours, distance))

    semantic_scores: dict[uuid.UUID, float] = {}
    if settings.semantic_report_matching_enabled and candidates:
        scored_reports = [candidate for candidate, _, _ in candidates]
        semantic_scores = dict(zip(
            (candidate.id for candidate in scored_reports),
            _semantic_scores(source, scored_reports),
        ))

    proposals = []
    for candidate, hours, distance in candidates:
        first_id, second_id = _pair_ids(source.id, candidate.id)
        relationship = db.scalar(select(ReportRelationshipRecord).where(
            ReportRelationshipRecord.report_id == first_id,
            ReportRelationshipRecord.related_report_id == second_id,
        ))
        if relationship is not None and relationship.status != "PROPOSED":
            continue

        evidence = {
            "time_difference_hours": round(hours, 3),
            "distance_km": round(distance, 3),
            "semantic_matching_enabled": settings.semantic_report_matching_enabled,
            "semantic_similarity": (
                round(semantic_scores[candidate.id], 4)
                if candidate.id in semantic_scores else None
            ),
        }
        if relationship is None:
            relationship = ReportRelationshipRecord(
                report_id=first_id,
                related_report_id=second_id,
                evidence=evidence,
                proposed_by=actor_id,
            )
            db.add(relationship)
        else:
            relationship.evidence = evidence
            relationship.proposed_by = actor_id
            relationship.proposed_at = utc_now()
        proposals.append(relationship)

    db.commit()
    for proposal in proposals:
        db.refresh(proposal)
    return proposals


def _report_out(db: Session, report_id: uuid.UUID) -> RelationshipReportOut:
    report = db.get(IncidentReport, report_id)
    if report is None:
        raise NotFound("A report in this relationship no longer exists.")
    return RelationshipReportOut(
        id=report.id,
        disaster_type=report.disaster_type,
        description=report.description,
        latitude=report.map_latitude,
        longitude=report.map_longitude,
        location_name=report.map_location_name,
        status=report.status,
        submitted_at=report.submitted_at,
    )


def relationship_output(db: Session, relationship: ReportRelationshipRecord) -> dict:
    return {
        "id": relationship.id,
        "report": _report_out(db, relationship.report_id),
        "related_report": _report_out(db, relationship.related_report_id),
        "status": relationship.status,
        "evidence": relationship.evidence,
        "proposed_by": relationship.proposed_by,
        "proposed_at": relationship.proposed_at,
        "decided_by": relationship.decided_by,
        "decided_at": relationship.decided_at,
        "decision_reason": relationship.decision_reason,
    }


def list_relationships(db: Session, status: str) -> list[dict]:
    relationships = db.scalars(
        select(ReportRelationshipRecord)
        .where(ReportRelationshipRecord.status == status)
        .order_by(ReportRelationshipRecord.proposed_at.desc())
        .limit(200)
    ).all()
    return [relationship_output(db, item) for item in relationships]


def decide_relationship(
    db: Session,
    relationship_id: uuid.UUID,
    actor_id: uuid.UUID,
    decision: str,
    reason: str | None,
) -> dict:
    relationship = db.get(ReportRelationshipRecord, relationship_id)
    if relationship is None:
        raise NotFound("Potential relationship not found.")
    if relationship.status != "PROPOSED":
        raise Conflict(f"Only proposed relationships can be decided (current status: {relationship.status}).")

    relationship.status = decision
    relationship.decided_by = actor_id
    relationship.decided_at = utc_now()
    relationship.decision_reason = reason.strip() if reason and reason.strip() else None
    db.add(WorkflowAudit(
        actor_id=actor_id,
        event_type=f"REPORT_RELATIONSHIP_{decision}",
        report_id=relationship.report_id,
        details={
            "relationship_id": str(relationship.id),
            "related_report_id": str(relationship.related_report_id),
            "decision_reason": relationship.decision_reason,
        },
    ))
    db.commit()
    db.refresh(relationship)
    return relationship_output(db, relationship)
