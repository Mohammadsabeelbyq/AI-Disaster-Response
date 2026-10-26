"""Report review, incident confirmation, and human-supervised response planning."""
import uuid
import logging
import time
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.config import get_settings
from app.models.incident import (
    Incident,
    IncidentPriorityOverride,
    IncidentReportLink,
    PriorityRuleConfig,
    ResponsePlan,
    WorkflowAudit,
)
from app.models.report_relationship import ReportRelationshipRecord
from app.models.resources import (
    Department,
    Resource,
    ResourceAssignment,
    ResourceAvailabilityEvent,
)
from app.models.user import User
from app.models.report import IncidentReport, ReportStatus
from app.services import resource_service
from app.services.errors import Conflict, NotFound, StorageFailure, ValidationFailed
from app.services.groq_planner import GroqPlanDraft, GroqPlannerError, generate_plan_draft
from app.services.media_service import delete_image
from app.services.resource_service import _incident_capabilities
from app.services.priority_service import (
    DEFAULT_PRIORITY_THRESHOLDS,
    DEFAULT_PRIORITY_WEIGHTS,
    PRIORITY_BANDS,
    PRIORITY_ALGORITHM_VERSION,
    calculate_priority_score,
    classify_priority,
    validate_priority_thresholds,
    validate_priority_weights,
)

logger = logging.getLogger(__name__)


def _audit(db: Session, actor_id: uuid.UUID, event_type: str, *, report_id=None,
           incident_id=None, plan_id=None, details=None) -> None:
    db.add(WorkflowAudit(
        actor_id=actor_id,
        event_type=event_type,
        report_id=report_id,
        incident_id=incident_id,
        plan_id=plan_id,
        details=details or {},
    ))


def _report_or_404(db: Session, report_id: uuid.UUID) -> IncidentReport:
    report = db.get(IncidentReport, report_id)
    if report is None:
        raise NotFound("Report not found.")
    return report


def _next_priority_version(db: Session) -> str:
    versions = db.scalars(select(PriorityRuleConfig.version)).all()
    numbers = [
        int(version[1:])
        for version in versions
        if version.startswith("v") and version[1:].isdigit()
    ]
    return f"v{max(numbers, default=0) + 1}"


def _get_admin_user(db: Session) -> uuid.UUID | None:
    user = db.scalar(select(User).where(User.role == "ADMIN").order_by(User.created_at.asc()))
    if user is None:
        user = db.scalar(select(User).order_by(User.created_at.asc()))
    return user.id if user else None


def get_active_priority_config(
    db: Session, created_by: uuid.UUID | None = None,
) -> PriorityRuleConfig:
    config = db.scalar(
        select(PriorityRuleConfig).where(PriorityRuleConfig.is_active.is_(True)).order_by(PriorityRuleConfig.created_at.desc())
    )
    if config is not None:
        return config

    default_weights = validate_priority_weights(DEFAULT_PRIORITY_WEIGHTS)
    default_thresholds = validate_priority_thresholds(DEFAULT_PRIORITY_THRESHOLDS)
    admin_id = created_by or _get_admin_user(db)
    if admin_id is None:
        raise ValidationFailed("Configure an administrator before initializing priority rules.")
    config = PriorityRuleConfig(
        version=_next_priority_version(db),
        is_active=True,
        weights=default_weights,
        thresholds=default_thresholds,
        notes="Default operational priority configuration",
        created_by=admin_id,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def create_priority_configuration(db: Session, actor_id: uuid.UUID, *, weights: dict, thresholds: dict,
                                  notes: str | None = None) -> PriorityRuleConfig:
    normalized_weights = validate_priority_weights(weights)
    normalized_thresholds = validate_priority_thresholds(thresholds)
    for existing in db.scalars(select(PriorityRuleConfig)):
        existing.is_active = False

    config = PriorityRuleConfig(
        version=_next_priority_version(db),
        is_active=True,
        weights=normalized_weights,
        thresholds=normalized_thresholds,
        notes=notes.strip() if notes else None,
        created_by=actor_id,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _band_from_score(score: float, thresholds: dict[str, float]) -> str:
    band = classify_priority(score, thresholds)
    if band is None:
        raise ValidationFailed("A priority band cannot be assigned without a score.")
    return band


def calculate_priority_for_incident(db: Session, incident: Incident) -> Incident:
    config = get_active_priority_config(db, created_by=incident.confirmed_by)
    extraction = incident.report.extraction if incident.report else None
    facts = dict(extraction.effective_facts) if extraction else {}
    score, factors, breakdown = calculate_priority_score(
        facts,
        getattr(extraction, "confidence", None) if extraction else None,
        config.weights,
    )
    incident.priority_score = score
    incident.priority_band = classify_priority(score, config.thresholds)
    incident.priority_rule_version = config.version
    incident.priority_algorithm_version = PRIORITY_ALGORITHM_VERSION
    incident.priority_factors = factors
    incident.priority_breakdown = breakdown
    incident.priority_calculated_at = datetime.now(timezone.utc)
    if score is not None and incident.priority_original_score is None:
        incident.priority_original_score = score
    if incident.priority_band is not None and incident.priority_original_band is None:
        incident.priority_original_band = incident.priority_band
    if not incident.priority_is_overridden:
        incident.priority_override_reason = None
        incident.priority_override_by = None
        incident.priority_override_at = None
    db.add(incident)
    db.flush()
    return incident


def override_incident_priority(db: Session, incident_id: uuid.UUID, actor_id: uuid.UUID, *, reason: str,
                              score: float | None = None, band: str | None = None) -> Incident:
    incident = get_incident(db, incident_id)
    reason_text = reason.strip()
    if not reason_text:
        raise ValidationFailed("A priority override reason is required.")
    if band is not None and band.upper() not in PRIORITY_BANDS:
        raise ValidationFailed("Invalid priority band. Use LOW, MEDIUM, HIGH or CRITICAL.")

    if incident.priority_original_score is None or incident.priority_original_band is None:
        incident.priority_original_score = incident.priority_score
        incident.priority_original_band = incident.priority_band

    final_score = float(score) if score is not None else float(incident.priority_score or 0.0)
    final_band = band.upper() if band else (incident.priority_band or _band_from_score(final_score, get_active_priority_config(db).thresholds))

    if final_band not in PRIORITY_BANDS:
        raise ValidationFailed("Invalid priority band. Use LOW, MEDIUM, HIGH or CRITICAL.")

    incident.priority_is_overridden = True
    incident.priority_override_reason = reason_text
    incident.priority_override_by = actor_id
    incident.priority_override_at = datetime.now(timezone.utc)
    incident.priority_score = final_score
    incident.priority_band = final_band
    db.add(incident)
    db.add(IncidentPriorityOverride(
        incident_id=incident.id,
        actor_id=actor_id,
        original_score=incident.priority_original_score,
        original_band=incident.priority_original_band,
        override_score=final_score,
        override_band=final_band,
        reason=reason_text,
    ))
    _audit(
        db,
        actor_id,
        "INCIDENT_PRIORITY_OVERRIDE",
        incident_id=incident.id,
        details={
            "from_score": incident.priority_original_score,
            "to_score": final_score,
            "from_band": incident.priority_original_band,
            "to_band": final_band,
            "reason": reason_text,
            "rule_version": incident.priority_rule_version,
        },
    )
    db.commit()
    db.refresh(incident)
    return incident


def confirm_report(db: Session, report_id: uuid.UUID, actor_id: uuid.UUID) -> Incident:
    report = _report_or_404(db, report_id)
    if report.status not in {ReportStatus.SUBMITTED, ReportStatus.UNDER_REVIEW}:
        raise Conflict(
            "Only submitted reports can be confirmed "
            f"(current status: {report.status})."
        )
    if report.incident is not None:
        raise Conflict("This report already has a confirmed incident.")

    incident = Incident(report=report, status="CONFIRMED", confirmed_by=actor_id)
    report.status = ReportStatus.ACCEPTED
    db.add(incident)
    db.flush()
    calculate_priority_for_incident(db, incident)
    _audit(db, actor_id, "INCIDENT_CONFIRMED", report_id=report.id,
           incident_id=incident.id, details={"report_status": ReportStatus.ACCEPTED})
    db.commit()
    return get_incident(db, incident.id)


def link_report_to_incident(db: Session, incident_id: uuid.UUID, report_id: uuid.UUID,
                            actor_id: uuid.UUID, reason: str,
                            potential_relationship_id: uuid.UUID | None = None) -> Incident:
    incident = get_incident(db, incident_id)
    report = _report_or_404(db, report_id)
    reason_text = reason.strip()
    if not reason_text:
        raise ValidationFailed("A reason is required to link a report.")
    if incident.status not in {"CONFIRMED", "ACTIVE"} or incident.merged_into_id is not None:
        raise Conflict("Reports can only be linked to an active canonical incident.")
    if report.id == incident.report_id:
        raise Conflict("A report cannot be linked to its own incident.")
    if report.incident_links:
        raise Conflict("This report is already associated with an incident.")

    potential_relationship = None
    if potential_relationship_id is not None:
        potential_relationship = db.get(ReportRelationshipRecord, potential_relationship_id)
        if potential_relationship is None:
            raise NotFound("Potential report relationship not found.")
        if potential_relationship.status != "PROPOSED":
            raise Conflict("Only proposed report relationships can be linked.")
        if {
            potential_relationship.report_id,
            potential_relationship.related_report_id,
        } != {report.id, incident.report_id}:
            raise Conflict(
                "The selected report and target incident do not match the proposed relationship."
            )

    source_incident = report.incident
    source_report_status = report.status
    source_incident_status = source_incident.status if source_incident is not None else None
    transferred_link_ids = []
    if source_incident is None:
        if report.status not in {ReportStatus.SUBMITTED, ReportStatus.UNDER_REVIEW}:
            raise Conflict(
                "Only submitted reports or confirmed incident reports can be linked "
                f"(current status: {report.status})."
            )
        report.status = "LINKED"
    else:
        if (
            source_incident.status not in {"CONFIRMED", "ACTIVE"}
            or source_incident.merged_into_id is not None
        ):
            raise Conflict("Only an unlinked open incident can be linked to a canonical incident.")
        if db.scalar(
            select(ResourceAssignment.id).where(
                ResourceAssignment.incident_id == source_incident.id,
                ResourceAssignment.released_at.is_(None),
            )
        ) is not None:
            raise Conflict("Release active resource assignments before linking this incident.")
        source_incident.status = "MERGED"
        source_incident.merged_into_id = incident.id

        source_links = db.scalars(
            select(IncidentReportLink).where(
                IncidentReportLink.incident_id == source_incident.id,
            )
        ).all()
        for link in source_links:
            link.incident_id = incident.id
            transferred_link_ids.append(str(link.id))
            if link.source_incident_id is None:
                link.source_incident_id = source_incident.id

    db.add(IncidentReportLink(
        incident_id=incident.id,
        report_id=report.id,
        source_incident_id=source_incident.id if source_incident is not None else None,
        relationship_type="LINKED_REPORT",
        linked_by=actor_id,
        reason=reason_text,
    ))
    _audit(
        db, actor_id, "REPORT_LINKED_TO_INCIDENT", report_id=report.id,
        incident_id=incident.id,
        details={
            "relationship_type": "LINKED_REPORT",
            "reason": reason_text,
            "source_incident_id": (
                str(source_incident.id) if source_incident is not None else None
            ),
            "source_report_status": source_report_status,
            "source_incident_status": source_incident_status,
            "transferred_link_ids": transferred_link_ids,
        },
    )
    if potential_relationship is not None:
        now = datetime.now(timezone.utc)
        potential_relationship.status = "CONFIRMED"
        potential_relationship.decided_by = actor_id
        potential_relationship.decided_at = now
        potential_relationship.decision_reason = reason_text
        _audit(
            db,
            actor_id,
            "REPORT_RELATIONSHIP_CONFIRMED",
            report_id=potential_relationship.report_id,
            incident_id=incident.id,
            details={
                "relationship_id": str(potential_relationship.id),
                "related_report_id": str(potential_relationship.related_report_id),
                "decision_reason": reason_text,
                "linked_report_id": str(report.id),
            },
        )
    db.commit()
    db.expire_all()
    return get_incident(db, incident.id)


def _merged_incident_descendants(db: Session, incident_id: uuid.UUID) -> set[uuid.UUID]:
    descendants = {incident_id}
    while True:
        child_ids = set(db.scalars(
            select(Incident.id).where(Incident.merged_into_id.in_(descendants))
        ).all())
        new_ids = child_ids - descendants
        if not new_ids:
            return descendants
        descendants.update(new_ids)


def _restore_merged_incident(
    db: Session,
    source: Incident,
    canonical: Incident,
    actor_id: uuid.UUID,
    reason: str,
) -> None:
    if source.status != "MERGED" or source.merged_into_id != canonical.id:
        raise Conflict("The source incident is no longer merged into this incident.")
    if db.scalar(
        select(ResourceAssignment.id).where(
            ResourceAssignment.incident_id == source.id,
            ResourceAssignment.released_at.is_(None),
        )
    ) is not None:
        raise Conflict("Release active resource assignments before unlinking this incident.")

    anchor = db.scalar(
        select(IncidentReportLink).where(
            IncidentReportLink.incident_id == canonical.id,
            IncidentReportLink.report_id == source.report_id,
            IncidentReportLink.source_incident_id == source.id,
        )
    )
    if anchor is None:
        raise Conflict("The merge link could not be verified; no changes were made.")

    link_event = db.scalar(
        select(WorkflowAudit)
        .where(
            WorkflowAudit.event_type == "REPORT_LINKED_TO_INCIDENT",
            WorkflowAudit.report_id == source.report_id,
            WorkflowAudit.incident_id == canonical.id,
        )
        .order_by(WorkflowAudit.created_at.desc())
    )
    previous_status = (
        link_event.details.get("source_incident_status")
        if link_event is not None else None
    )
    if previous_status not in {"CONFIRMED", "ACTIVE"}:
        previous_status = "ACTIVE"

    descendants = _merged_incident_descendants(db, source.id)
    links = db.scalars(
        select(IncidentReportLink)
        .options(
            joinedload(IncidentReportLink.report)
            .joinedload(IncidentReport.incident)
        )
        .where(IncidentReportLink.incident_id == canonical.id)
    ).unique().all()
    restored_link_ids = []
    for link in links:
        if link.id == anchor.id:
            continue
        report_incident = link.report.incident
        belongs_to_source = (
            link.source_incident_id in descendants
            or (report_incident is not None and report_incident.id in descendants)
        )
        if not belongs_to_source:
            continue
        link.incident_id = source.id
        if link.source_incident_id == source.id:
            link.source_incident_id = None
        restored_link_ids.append(str(link.id))

    db.delete(anchor)
    source.status = previous_status
    source.merged_into_id = None
    _audit(
        db,
        actor_id,
        "INCIDENT_UNMERGED_FROM_CANONICAL",
        incident_id=source.id,
        details={
            "canonical_incident_id": str(canonical.id),
            "reason": reason,
            "restored_link_ids": restored_link_ids,
        },
    )
    db.flush()


def unlink_report_from_incident(
    db: Session,
    incident_id: uuid.UUID,
    report_id: uuid.UUID,
    actor_id: uuid.UUID,
    reason: str,
) -> Incident:
    incident = get_incident(db, incident_id)
    report = _report_or_404(db, report_id)
    reason_text = reason.strip()
    if not reason_text:
        raise ValidationFailed("A reason is required to unlink a report.")

    link = db.scalar(
        select(IncidentReportLink).where(
            IncidentReportLink.incident_id == incident.id,
            IncidentReportLink.report_id == report.id,
        )
    )
    if link is None:
        raise NotFound("This report is not linked to the selected incident.")

    source_incident = report.incident
    if source_incident is not None:
        _restore_merged_incident(
            db, source_incident, incident, actor_id, reason_text,
        )
    else:
        link_event = db.scalar(
            select(WorkflowAudit)
            .where(
                WorkflowAudit.event_type == "REPORT_LINKED_TO_INCIDENT",
                WorkflowAudit.report_id == report.id,
                WorkflowAudit.incident_id == incident.id,
            )
            .order_by(WorkflowAudit.created_at.desc())
        )
        previous_status = (
            link_event.details.get("source_report_status")
            if link_event is not None else None
        )
        report.status = (
            previous_status
            if previous_status in {ReportStatus.SUBMITTED, ReportStatus.UNDER_REVIEW}
            else ReportStatus.SUBMITTED
        )
        db.delete(link)

    _audit(
        db,
        actor_id,
        "REPORT_UNLINKED_FROM_INCIDENT",
        report_id=report.id,
        incident_id=incident.id,
        details={
            "reason": reason_text,
            "source_incident_id": (
                str(source_incident.id) if source_incident is not None else None
            ),
        },
    )
    db.commit()
    db.expire_all()
    return get_incident(db, incident.id)


def delete_report(
    db: Session,
    report_id: uuid.UUID,
    actor_id: uuid.UUID,
    reason: str,
) -> None:
    report = _report_or_404(db, report_id)
    reason_text = reason.strip()
    if not reason_text:
        raise ValidationFailed("A reason is required to delete a report.")

    media_paths = [media.storage_path for media in report.media]
    incident = report.incident
    if incident is not None:
        incident = db.scalar(
            select(Incident)
            .options(selectinload(Incident.plans).selectinload(ResponsePlan.assignments))
            .where(Incident.id == incident.id)
        )
        if incident.merged_into_id is not None:
            canonical = db.get(Incident, incident.merged_into_id)
            if canonical is None:
                raise Conflict("The canonical incident could not be found; report was not deleted.")
            _restore_merged_incident(
                db, incident, canonical, actor_id, reason_text,
            )
        else:
            merged_children = db.scalars(
                select(Incident).where(Incident.merged_into_id == incident.id)
            ).all()
            for child in merged_children:
                _restore_merged_incident(
                    db, child, incident, actor_id, reason_text,
                )

        linked_reports = db.scalars(
            select(IncidentReportLink)
            .options(joinedload(IncidentReportLink.report))
            .where(IncidentReportLink.incident_id == incident.id)
        ).unique().all()
        for link in linked_reports:
            linked_report = link.report
            if linked_report.id != report.id and linked_report.incident is None:
                linked_report.status = ReportStatus.SUBMITTED

        assignments = [
            assignment
            for plan in incident.plans
            for assignment in plan.assignments
        ]
        now = datetime.now(timezone.utc)
        for assignment in assignments:
            if assignment.released_at is None:
                _release_assignment(db, assignment, actor_id, reason_text, now)
            db.delete(assignment)

    db.execute(
        delete(ReportRelationshipRecord).where(
            or_(
                ReportRelationshipRecord.report_id == report.id,
                ReportRelationshipRecord.related_report_id == report.id,
            )
        )
    )
    _audit(
        db,
        actor_id,
        "REPORT_DELETED",
        details={
            "report_id": str(report.id),
            "incident_id": str(incident.id) if incident is not None else None,
            "reason": reason_text,
        },
    )
    db.delete(report)
    db.commit()
    cleanup_errors = []
    for storage_path in media_paths:
        try:
            delete_image(storage_path, strict=True)
        except StorageFailure as exc:
            cleanup_errors.append(exc)
    if cleanup_errors:
        raise StorageFailure(
            "The report was deleted, but one or more attached images could not be removed."
        ) from cleanup_errors[0]


def dismiss_report(db: Session, report_id: uuid.UUID, actor_id: uuid.UUID,
                   reason: str | None = None) -> IncidentReport:
    report = _report_or_404(db, report_id)
    if report.status not in {ReportStatus.SUBMITTED, ReportStatus.UNDER_REVIEW}:
        raise Conflict(
            "Only submitted reports can be dismissed "
            f"(current status: {report.status})."
        )
    report.status = ReportStatus.DISMISSED
    _audit(db, actor_id, "REPORT_DISMISSED", report_id=report.id,
           details={"reason": reason or "", "to": ReportStatus.DISMISSED})
    db.commit()
    db.refresh(report)
    return report


def reopen_dismissed_report(db: Session, report_id: uuid.UUID, actor_id: uuid.UUID,
                            reason: str) -> IncidentReport:
    report = _report_or_404(db, report_id)
    reason_text = reason.strip()
    if not reason_text:
        raise ValidationFailed("A reason is required to reopen a dismissed report.")
    if report.status != ReportStatus.DISMISSED:
        raise Conflict(
            "Only DISMISSED reports can be reopened "
            f"(current status: {report.status})."
        )
    if report.incident is not None or report.incident_links:
        raise Conflict("A report linked to an incident cannot be reopened.")

    report.status = ReportStatus.SUBMITTED
    _audit(
        db,
        actor_id,
        "REPORT_REOPENED",
        report_id=report.id,
        details={
            "reason": reason_text,
            "from": ReportStatus.DISMISSED,
            "to": ReportStatus.SUBMITTED,
        },
    )
    db.commit()
    db.refresh(report)
    return report


def close_incident(db: Session, incident_id: uuid.UUID, actor_id: uuid.UUID,
                   reason: str) -> Incident:
    incident = get_incident(db, incident_id)
    reason_text = reason.strip()
    if not reason_text:
        raise ValidationFailed("A reason is required to close an incident.")
    if incident.status not in {"CONFIRMED", "ACTIVE"} or incident.merged_into_id is not None:
        raise Conflict("Only open, canonical incidents can be closed.")
    active_assignment = db.scalar(
        select(ResourceAssignment.id)
        .where(
            ResourceAssignment.incident_id == incident.id,
            ResourceAssignment.released_at.is_(None),
        )
        .limit(1)
    )
    if active_assignment is not None:
        raise Conflict("Release active resource assignments before closing this incident.")
    incident.status = "CLOSED"
    _audit(
        db, actor_id, "INCIDENT_CLOSED", report_id=incident.report_id,
        incident_id=incident.id, details={"reason": reason_text},
    )
    db.commit()
    db.expire_all()
    return get_incident(db, incident.id)


def reopen_incident(db: Session, incident_id: uuid.UUID, actor_id: uuid.UUID,
                    reason: str) -> Incident:
    incident = get_incident(db, incident_id)
    reason_text = reason.strip()
    if not reason_text:
        raise ValidationFailed("A reason is required to reopen an incident.")
    if incident.status != "CLOSED" or incident.merged_into_id is not None:
        raise Conflict("Only closed, canonical incidents can be reopened.")
    incident.status = "ACTIVE"
    _audit(
        db, actor_id, "INCIDENT_REOPENED", report_id=incident.report_id,
        incident_id=incident.id, details={"reason": reason_text},
    )
    db.commit()
    db.expire_all()
    return get_incident(db, incident.id)


def list_incidents(db: Session) -> list[Incident]:
    return list(db.scalars(
        select(Incident).options(
            joinedload(Incident.plans),
            joinedload(Incident.report).joinedload(IncidentReport.location_correction),
            selectinload(Incident.report_links),
        ).where(Incident.merged_into_id.is_(None)).order_by(Incident.confirmed_at.desc())
    ).unique())


def get_incident(db: Session, incident_id: uuid.UUID) -> Incident:
    incident = db.scalar(
        select(Incident).options(
            joinedload(Incident.plans),
            joinedload(Incident.report).joinedload(IncidentReport.location_correction),
            selectinload(Incident.report_links),
        ).where(Incident.id == incident_id)
    )
    if incident is None:
        raise NotFound("Incident not found.")
    return incident


def list_priority_configs(db: Session) -> list[PriorityRuleConfig]:
    return list(db.scalars(select(PriorityRuleConfig).order_by(PriorityRuleConfig.created_at.desc())).all())


def get_response_plan(db: Session, plan_id: uuid.UUID) -> ResponsePlan:
    plan = db.get(ResponsePlan, plan_id)
    if plan is None:
        raise NotFound("Response plan not found.")
    return plan


def assign_response_plan_resources(
    db: Session,
    plan_id: uuid.UUID,
    actor_id: uuid.UUID,
    resource_ids: list[uuid.UUID],
    reason: str,
) -> ResponsePlan:
    plan = get_response_plan(db, plan_id)
    if plan.status != "APPROVED":
        raise Conflict("Resources can only be assigned from an approved response plan.")
    incident = get_incident(db, plan.incident_id)
    if incident.status not in {"CONFIRMED", "ACTIVE"} or incident.merged_into_id is not None:
        raise Conflict("Resources can only be assigned to an active canonical incident.")

    reason_text = reason.strip()
    if not reason_text:
        raise ValidationFailed("An assignment reason is required.")
    if len(resource_ids) != len(set(resource_ids)):
        raise ValidationFailed("Each resource can be assigned only once per request.")

    recommended_ids = {
        str(candidate["id"])
        for candidate in plan.resource_candidates
        if isinstance(candidate, dict) and candidate.get("id")
    }
    requested_ids = {str(resource_id) for resource_id in resource_ids}
    registered_resources = {
        resource.id: resource
        for resource in db.scalars(
            select(Resource).where(Resource.id.in_(resource_ids))
        ).all()
    }
    missing_ids = set(resource_ids) - registered_resources.keys()
    if missing_ids:
        raise ValidationFailed("One or more selected resources are not registered.")

    active_assignment = select(ResourceAssignment.id).where(
        ResourceAssignment.resource_id == Resource.id,
        ResourceAssignment.released_at.is_(None),
    ).exists()
    current_resources = {
        resource.id: resource
        for resource in db.scalars(
            select(Resource)
            .join(Department, Resource.department_id == Department.id)
            .where(
                Resource.id.in_(resource_ids),
                Resource.availability == "AVAILABLE",
                Department.is_active.is_(True),
                Resource.resource_type.is_not(None),
                Resource.latitude.is_not(None),
                Resource.longitude.is_not(None),
                ~active_assignment,
            )
            .with_for_update()
        ).all()
    }
    if not set(resource_ids) <= current_resources.keys():
        raise Conflict(
            "One or more selected resources are no longer available or operationally eligible. "
            "Refresh the resource list before assigning."
        )

    now = datetime.now(timezone.utc)
    assigned_ids = []
    for resource_id in resource_ids:
        resource = current_resources[resource_id]
        result = db.execute(
            update(Resource)
            .where(
                Resource.id == resource_id,
                Resource.availability == "AVAILABLE",
                Resource.department_id.in_(
                    select(Department.id).where(Department.is_active.is_(True))
                ),
            )
            .values(availability="ASSIGNED", updated_at=now)
        )
        if result.rowcount != 1:
            db.rollback()
            raise Conflict(
                f"Resource {resource.code} became unavailable before assignment. "
                "Refresh the response plan and try again."
            )

        db.add(ResourceAssignment(
            resource_id=resource.id,
            incident_id=incident.id,
            plan_id=plan.id,
            assigned_by=actor_id,
            assigned_at=now,
            reason=reason_text,
        ))
        db.add(ResourceAvailabilityEvent(
            resource_id=resource.id,
            changed_by=actor_id,
            previous_availability="AVAILABLE",
            new_availability="ASSIGNED",
            reason=reason_text,
            changed_at=now,
        ))
        assigned_ids.append(str(resource.id))

    _audit(
        db,
        actor_id,
        "RESOURCES_ASSIGNED",
        incident_id=incident.id,
        plan_id=plan.id,
        details={
            "resource_ids": assigned_ids,
            "recommended_resource_ids": [
                resource_id for resource_id in assigned_ids
                if resource_id in recommended_ids
            ],
            "coordinator_selected_nonrecommended_resource_ids": [
                resource_id for resource_id in assigned_ids
                if resource_id not in recommended_ids
            ],
            "reason": reason_text,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("A resource was assigned concurrently. Refresh the response plan.") from exc
    return get_response_plan(db, plan.id)


def release_response_plan_assignment(
    db: Session,
    plan_id: uuid.UUID,
    assignment_id: uuid.UUID,
    actor_id: uuid.UUID,
    reason: str,
) -> ResponsePlan:
    plan = get_response_plan(db, plan_id)
    assignment = db.scalar(
        select(ResourceAssignment).where(
            ResourceAssignment.id == assignment_id,
            ResourceAssignment.plan_id == plan.id,
        )
    )
    if assignment is None:
        raise NotFound("Resource assignment not found for this response plan.")
    if assignment.released_at is not None:
        raise Conflict("This resource assignment has already been released.")

    reason_text = reason.strip()
    if not reason_text:
        raise ValidationFailed("A release reason is required.")
    _release_assignment(db, assignment, actor_id, reason_text, datetime.now(timezone.utc))
    db.commit()
    return get_response_plan(db, plan.id)


def _release_assignment(
    db: Session,
    assignment: ResourceAssignment,
    actor_id: uuid.UUID,
    reason: str,
    now: datetime,
) -> None:
    resource = db.get(Resource, assignment.resource_id)
    if resource is None:
        raise NotFound("The assigned resource no longer exists.")

    result = db.execute(
        update(Resource)
        .where(
            Resource.id == resource.id,
            Resource.availability == "ASSIGNED",
        )
        .values(availability="AVAILABLE", updated_at=now)
    )
    if result.rowcount != 1:
        db.rollback()
        raise Conflict("The resource state changed; refresh before releasing this assignment.")

    resource.availability = "AVAILABLE"
    assignment.released_by = actor_id
    assignment.released_at = now
    assignment.release_reason = reason
    db.add(ResourceAvailabilityEvent(
        resource_id=resource.id,
        changed_by=actor_id,
        previous_availability="ASSIGNED",
        new_availability="AVAILABLE",
        reason=reason,
        changed_at=now,
    ))
    _audit(
        db,
        actor_id,
        "RESOURCE_ASSIGNMENT_RELEASED",
        incident_id=assignment.incident_id,
        plan_id=assignment.plan_id,
        details={
            "assignment_id": str(assignment.id),
            "resource_id": str(assignment.resource_id),
            "reason": reason,
        },
    )


def make_all_resources_available(
    db: Session,
    actor_id: uuid.UUID,
    reason: str,
) -> dict:
    reason_text = reason.strip()
    if not reason_text:
        raise ValidationFailed("A reason is required to make resources available.")

    now = datetime.now(timezone.utc)
    resources = db.scalars(
        select(Resource)
        .options(joinedload(Resource.department))
        .order_by(Resource.code)
        .with_for_update()
    ).unique().all()
    active_assignments = db.scalars(
        select(ResourceAssignment)
        .where(ResourceAssignment.released_at.is_(None))
        .with_for_update()
    ).all()
    assignments_by_resource = {
        assignment.resource_id: assignment for assignment in active_assignments
    }

    made_available = 0
    already_available = 0
    released_assignment_ids = []
    changed_resource_ids = []
    skipped = []

    for resource in resources:
        assignment = assignments_by_resource.get(resource.id)
        if assignment is not None:
            _release_assignment(db, assignment, actor_id, reason_text, now)
            made_available += 1
            released_assignment_ids.append(str(assignment.id))
            changed_resource_ids.append(str(resource.id))
            continue

        if resource.availability == "AVAILABLE":
            already_available += 1
            continue
        if not resource.department.is_active:
            skipped.append({
                "resource_id": resource.id,
                "code": resource.code,
                "reason": "The owning department is inactive.",
            })
            continue
        if resource.resource_type is None or resource.latitude is None or resource.longitude is None:
            skipped.append({
                "resource_id": resource.id,
                "code": resource.code,
                "reason": "Complete the resource type and location before making it available.",
            })
            continue

        previous = resource.availability
        resource.availability = "AVAILABLE"
        resource.updated_at = now
        db.add(ResourceAvailabilityEvent(
            resource_id=resource.id,
            changed_by=actor_id,
            previous_availability=previous,
            new_availability="AVAILABLE",
            reason=reason_text,
            changed_at=now,
        ))
        made_available += 1
        changed_resource_ids.append(str(resource.id))

    _audit(
        db,
        actor_id,
        "RESOURCES_MADE_AVAILABLE",
        details={
            "reason": reason_text,
            "resource_ids": changed_resource_ids,
            "released_assignment_ids": released_assignment_ids,
            "already_available_count": already_available,
            "skipped": [
                {
                    "resource_id": str(item["resource_id"]),
                    "code": item["code"],
                    "reason": item["reason"],
                }
                for item in skipped
            ],
        },
    )
    db.commit()
    return {
        "resources_made_available": made_available,
        "already_available_count": already_available,
        "released_assignment_count": len(released_assignment_ids),
        "skipped": skipped,
    }


def _recommend_actions(facts: dict) -> tuple[list[str], list[str]]:
    actions = ["Coordinator: verify the submitted information and assess current conditions before response."]
    requirements = []

    urgency = facts.get("urgency")
    if urgency in {"CRITICAL", "HIGH"}:
        actions.append("Prioritize life-safety triage and confirm immediate hazards.")

    for hazard in facts.get("hazards", []):
        requirements.append(f"Assess reported hazard: {hazard.replace('_', ' ').lower()}.")
    for request in facts.get("requested_assistance", []):
        requirements.append(f"Review request for {request.replace('_', ' ').lower()} support.")
    if facts.get("affected_persons") is not None:
        actions.append(f"Verify the reported affected-person count ({facts['affected_persons']}).")
    if facts.get("location_mentions"):
        actions.append("Verify the incident location and access conditions.")

    actions.extend(requirements)
    if len(actions) == 1:
        actions.append("Gather verified incident details and determine response needs.")
    return actions, requirements


def recheck_resource_availability(
    db: Session,
    candidate_ids: list[uuid.UUID],
) -> tuple[list[Resource], list[uuid.UUID]]:
    """Recheck candidate state; a draft recommendation is not itself an assignment."""
    db.expire_all()
    available_resources = []
    dropped_ids = []

    for cid in candidate_ids:
        res = db.get(Resource, cid)
        if res is None:
            dropped_ids.append(cid)
            continue
        if res.availability != "AVAILABLE" or not res.department.is_active:
            dropped_ids.append(cid)
            continue
        available_resources.append(res)

    return available_resources, dropped_ids


def evaluate_grounded_resources(
    db: Session,
    incident: Incident,
) -> tuple[list[tuple[Resource, int, list[str]]], list[str]]:
    """
    Evaluate registered database resources against incident constraints:
    - capabilities (required incident capabilities from requested assistance, hazards, disaster type)
    - location (within impact area radius / polygon if set, or default operational radius; exclude unlocated)
    - availability (status == AVAILABLE, not UNAVAILABLE or INACTIVE)
    - assignment status (exclude BUSY, DEPLOYED, ASSIGNED, or active in another plan)
    Returns (candidate_matches, constraints_considered).
    """
    constraints_considered = [
        "Required capability",
        "Resource availability",
        "Assignment status",
        "Location",
    ]

    _, _, matches = resource_service.find_resource_matches(db, incident)
    return matches, constraints_considered


def _build_grounded_response_data(
    finalized_candidates: list[tuple[Resource, int, list[str]]],
    required_capabilities: list[str],
    search_radius: float,
) -> tuple[list[dict], dict, str, list[dict]]:
    """Build resource_candidates, response_option, rationale, and evidence for FR-28 and FR-29."""
    if finalized_candidates:
        resource_candidates = [
            {
                "id": str(res.id),
                "resource_id": str(res.id),
                "code": res.code,
                "name": res.name,
                "type": res.resource_type or "Unknown",
                "department_id": str(res.department_id),
                "department_code": res.department.code,
                "department_name": res.department.name,
                "capability": ", ".join(res.capabilities) if res.capabilities else "Unknown",
                "capabilities": res.capabilities,
                "status": res.availability,
                "distance_m": dist,
                "latitude": float(res.latitude) if res.latitude is not None else None,
                "longitude": float(res.longitude) if res.longitude is not None else None,
                "matching_capabilities": matching_caps,
                "matched_capabilities": matching_caps,
            }
            for res, dist, matching_caps in finalized_candidates
        ]

        response_option = {
            "resources": [
                {
                    "resource_id": str(res.id),
                    "code": res.code,
                    "name": res.name,
                    "type": res.resource_type or "Unknown",
                    "department_id": str(res.department_id),
                    "department_code": res.department.code,
                    "department_name": res.department.name,
                    "capability": ", ".join(res.capabilities) if res.capabilities else "Unknown",
                    "capabilities": res.capabilities,
                    "status": res.availability.lower(),
                    "distance_m": dist,
                }
                for res, dist, matching_caps in finalized_candidates
            ]
        }

        reasons = [
            f"'{res.name}' ({res.code}, {res.department.name}; type: {res.resource_type or 'Unknown'}) "
            f"matches required capabilities ({', '.join(matching_caps)}) at distance {dist}m "
            f"with verified {res.availability} availability"
            for res, dist, matching_caps in finalized_candidates
        ]
        rationale = (
            f"Recommended {len(finalized_candidates)} suitable resource(s) grounded in registered database records: "
            + "; ".join(reasons)
            + "."
        )

        evidence = [
            {
                "resource_id": str(res.id),
                "facts": [
                    f"Resource '{res.name}' ({res.code}) exists in registered database under department '{res.department.name}' (ID: {res.id}).",
                    f"Operational availability verified (availability: '{res.availability}').",
                    f"Capabilities {res.capabilities} match incident requirements: {matching_caps}.",
                    f"Location verified: coordinates ({float(res.latitude):.4f}, {float(res.longitude):.4f}), distance is {dist} metres from incident (within constraint radius {int(search_radius)} metres).",
                    f"Resource type: {res.resource_type}" if res.resource_type else "Resource type: Unknown (not registered in database record).",
                ],
            }
            for res, dist, matching_caps in finalized_candidates
        ]
    else:
        resource_candidates = []
        response_option = {"resources": []}
        rationale = "No suitable registered resources were found in the database matching the required capabilities, availability status, and location constraints."
        evidence = []

    return resource_candidates, response_option, rationale, evidence


def get_resource_recommendations(db: Session, incident: Incident) -> dict:
    candidates, constraints_considered = evaluate_grounded_resources(db, incident)
    candidate_ids = [resource.id for resource, _, _ in candidates]
    available_resources, _ = recheck_resource_availability(
        db, candidate_ids)
    available_ids = {resource.id for resource in available_resources}
    finalized = [item for item in candidates if item[0].id in available_ids]
    search_radius, _, _ = resource_service.find_resource_matches(db, incident)
    required_capabilities = _incident_capabilities(incident)
    _, response_option, rationale, evidence = _build_grounded_response_data(
        finalized, required_capabilities, search_radius)
    return {
        "response_option": response_option,
        "constraints_considered": constraints_considered,
        "rationale": rationale,
        "evidence": evidence,
    }


def _resource_gaps(resource_candidates: list[dict], required_capabilities: list[str],
                   requirements: list[str]) -> list[str]:
    if not resource_candidates:
        return [
            "No available registered resource was found; no suitable registered resources matched the required capabilities and location constraints, so no specific responders are named or assigned.",
            *requirements,
        ]

    covered = {
        capability
        for candidate in resource_candidates
        for capability in candidate.get("matching_capabilities", [])
    }
    unmet = set(required_capabilities) - covered
    gaps = []
    if unmet:
        gaps.append(f"Unmet incident capability requirements: {', '.join(sorted(unmet))}.")
    gaps.extend(requirements)
    return gaps


def _request_groq_plan(incident: Incident, facts: dict,
                       candidates: list[tuple[Resource, int, list[str]]],
                       constraints: list[str]) -> tuple[GroqPlanDraft | None, str | None]:
    settings = get_settings()
    if not settings.groq_api_key:
        return None, None

    area = incident.impact_area
    linked_reports = []
    for link in incident.report_links:
        report = link.report
        if report.id == incident.report_id:
            continue
        extraction = report.extraction
        linked_reports.append({
            "report_id": str(report.id),
            "relationship_type": link.relationship_type,
            "disaster_type": report.disaster_type,
            "description": report.description,
            "effective_facts": (
                dict(extraction.effective_facts) if extraction is not None else {}
            ),
            "location": {
                "latitude": float(report.map_latitude) if report.map_latitude is not None else None,
                "longitude": float(report.map_longitude) if report.map_longitude is not None else None,
                "location_name": report.map_location_name,
            },
        })
    snapshot = {
        "incident": {
            "id": str(incident.id),
            "disaster_type": incident.report.disaster_type,
            "description": incident.report.description,
            "corrected_facts": facts,
            "priority": {
                "score": incident.priority_score,
                "band": incident.priority_band,
            },
        },
        "linked_reports": linked_reports,
        "region": {
            "latitude": float(incident.report.map_latitude),
            "longitude": float(incident.report.map_longitude),
            "location_name": incident.report.map_location_name,
            "impact_area": ({
                "geometry_type": area.geometry_type,
                "radius_m": area.radius_m,
                "polygon": area.polygon,
            } if area is not None else None),
        },
        "constraints": constraints,
        "eligible_resources": [
            {
                "id": str(resource.id),
                "code": resource.code,
                "name": resource.name,
                "type": resource.resource_type,
                "department_id": str(resource.department_id),
                "department": resource.department.name,
                "availability": resource.availability,
                "capabilities": resource.capabilities,
                "location": {
                    "latitude": float(resource.latitude),
                    "longitude": float(resource.longitude),
                },
                "distance_m": distance,
                "matched_capabilities": matched,
            }
            for resource, distance, matched in candidates[:settings.groq_max_resources]
        ],
    }
    allowed_ids = {str(resource.id) for resource, _, _ in candidates[:settings.groq_max_resources]}
    for attempt in range(2):
        try:
            draft = generate_plan_draft(
                snapshot,
                api_key=settings.groq_api_key,
                model=settings.groq_model,
                timeout_seconds=settings.groq_timeout_seconds,
                max_tokens=settings.groq_max_tokens,
                temperature=settings.groq_temperature,
            )
        except GroqPlannerError:
            if attempt == 0:
                logger.info("Retrying Groq plan generation after provider failure.")
                time.sleep(0.5)
            continue

        if (len(draft.resource_ids) != len(set(draft.resource_ids))
                or not set(draft.resource_ids) <= allowed_ids):
            logger.warning(
                "Groq plan draft referenced duplicate or ineligible resource IDs "
                "(attempt %s/2).", attempt + 1,
            )
            if attempt == 0:
                time.sleep(0.5)
            continue
        return draft, settings.groq_model

    logger.warning("Groq plan generation failed after one retry; using deterministic planning.")
    return None, None


def generate_response_plan(
    db: Session,
    incident_id: uuid.UUID,
    actor_id: uuid.UUID,
    pre_finalize_hook: Callable[[], None] | None = None,
) -> ResponsePlan:
    incident = get_incident(db, incident_id)
    if incident.status not in {"CONFIRMED", "ACTIVE"}:
        raise Conflict("A response plan can only be generated for a confirmed or active incident.")
    extraction = incident.report.extraction
    if extraction is None:
        raise Conflict("This incident has no structured extraction to plan from.")

    facts = dict(extraction.effective_facts)
    actions, requirements = _recommend_actions(facts)
    candidates, constraints_considered = evaluate_grounded_resources(db, incident)
    if pre_finalize_hook:
        pre_finalize_hook()

    candidate_ids = [res.id for res, _, _ in candidates]
    available_resources, dropped_ids = recheck_resource_availability(
        db, candidate_ids
    )
    available_id_set = {r.id for r in available_resources}
    finalized_candidates = [
        (res, dist, matching) for res, dist, matching in candidates
        if res.id in available_id_set
    ]

    search_radius, _, _ = resource_service.find_resource_matches(db, incident)
    required_capabilities = _incident_capabilities(incident)
    groq_draft, groq_model = _request_groq_plan(
        incident, facts, finalized_candidates, constraints_considered)
    fresh_candidates, constraints_considered = evaluate_grounded_resources(db, incident)
    fresh_ids = [candidate[0].id for candidate in fresh_candidates]
    fresh_resources, _ = recheck_resource_availability(
        db, fresh_ids)
    fresh_resource_ids = {resource.id for resource in fresh_resources}
    finalized_candidates = [
        candidate for candidate in fresh_candidates
        if candidate[0].id in fresh_resource_ids
    ]
    if groq_draft is not None:
        selected_ids = set(groq_draft.resource_ids)
        fresh_by_id = {str(candidate[0].id): candidate for candidate in finalized_candidates}
        if selected_ids <= fresh_by_id.keys():
            finalized_candidates = [
                fresh_by_id[resource_id] for resource_id in selected_ids
            ]
            actions = groq_draft.recommended_actions
            planner_provider = "GROQ"
            rationale_override = groq_draft.rationale
        else:
            actions, requirements = _recommend_actions(facts)
            planner_provider = "DETERMINISTIC"
            groq_model = None
            rationale_override = None
    else:
        planner_provider = "DETERMINISTIC"
        groq_model = None
        rationale_override = None

    resource_candidates, response_option, rationale, evidence = _build_grounded_response_data(
        finalized_candidates, required_capabilities, search_radius
    )
    if rationale_override:
        rationale = rationale_override
    gaps = _resource_gaps(resource_candidates, required_capabilities, requirements)

    latest_version = db.scalar(
        select(func.max(ResponsePlan.version)).where(ResponsePlan.incident_id == incident.id)
    ) or 0
    plan = ResponsePlan(
        incident_id=incident.id,
        version=latest_version + 1,
        status="AWAITING_APPROVAL",
        source_facts=facts,
        recommended_actions=actions,
        resource_candidates=resource_candidates,
        response_option=response_option,
        constraints_considered=constraints_considered,
        rationale=rationale,
        evidence=evidence,
        gaps=gaps,
        planner_provider=planner_provider,
        planner_model=groq_model,
        human_approval_required=True,
        generated_by=actor_id,
    )
    db.add(plan)
    db.flush()
    _audit(db, actor_id, "RESPONSE_PLAN_GENERATED", incident_id=incident.id,
           plan_id=plan.id, details={"version": plan.version, "status": plan.status,
                                     "source_facts": facts,
                                     "recommended_resource_count": len(resource_candidates)})
    db.commit()
    db.refresh(plan)
    return plan


def decide_response_plan(db: Session, plan_id: uuid.UUID, actor_id: uuid.UUID,
                         decision: str, reason: str | None = None) -> ResponsePlan:
    plan = db.get(ResponsePlan, plan_id)
    if plan is None:
        raise NotFound("Response plan not found.")
    incident = get_incident(db, plan.incident_id)
    if incident.status not in {"CONFIRMED", "ACTIVE"} or incident.merged_into_id is not None:
        raise Conflict("Only plans for open, canonical incidents can be decided.")
    if plan.status != "AWAITING_APPROVAL":
        raise Conflict(f"Only AWAITING_APPROVAL plans can be decided (current status: {plan.status}).")
    if decision not in {"APPROVED", "REJECTED"}:
        raise ValueError("Decision must be APPROVED or REJECTED.")

    plan.status = decision
    plan.decided_by = actor_id
    plan.decided_at = datetime.now(timezone.utc)
    plan.decision_reason = reason
    _audit(db, actor_id, f"RESPONSE_PLAN_{decision}", incident_id=plan.incident_id,
           plan_id=plan.id, details={"reason": reason or "", "status": decision})
    db.commit()
    db.refresh(plan)
    return plan