"""Report review, incident confirmation, and human-supervised response planning."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models.incident import Incident, IncidentPriorityOverride, PriorityRuleConfig, ResponsePlan, WorkflowAudit
from app.models.user import User
from app.models.report import IncidentReport, ReportStatus
from app.services.errors import Conflict, NotFound, ValidationFailed
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


def start_report_review(db: Session, report_id: uuid.UUID, actor_id: uuid.UUID) -> IncidentReport:
    report = _report_or_404(db, report_id)
    if report.status != ReportStatus.SUBMITTED:
        raise Conflict(f"Only SUBMITTED reports can enter review (current status: {report.status}).")
    report.status = ReportStatus.UNDER_REVIEW
    _audit(db, actor_id, "REPORT_REVIEW_STARTED", report_id=report.id,
           details={"from": ReportStatus.SUBMITTED, "to": ReportStatus.UNDER_REVIEW})
    db.commit()
    db.refresh(report)
    return report


def confirm_report(db: Session, report_id: uuid.UUID, actor_id: uuid.UUID) -> Incident:
    report = _report_or_404(db, report_id)
    if report.status != ReportStatus.UNDER_REVIEW:
        raise Conflict(f"Only UNDER_REVIEW reports can be confirmed (current status: {report.status}).")
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


def dismiss_report(db: Session, report_id: uuid.UUID, actor_id: uuid.UUID,
                   reason: str | None = None) -> IncidentReport:
    report = _report_or_404(db, report_id)
    if report.status != ReportStatus.UNDER_REVIEW:
        raise Conflict(f"Only UNDER_REVIEW reports can be dismissed (current status: {report.status}).")
    report.status = ReportStatus.DISMISSED
    _audit(db, actor_id, "REPORT_DISMISSED", report_id=report.id,
           details={"reason": reason or "", "to": ReportStatus.DISMISSED})
    db.commit()
    db.refresh(report)
    return report


def list_incidents(db: Session) -> list[Incident]:
    return list(db.scalars(
        select(Incident).options(
            joinedload(Incident.plans),
            joinedload(Incident.report).joinedload(IncidentReport.location_correction),
        ).order_by(Incident.confirmed_at.desc())
    ).unique())


def get_incident(db: Session, incident_id: uuid.UUID) -> Incident:
    incident = db.scalar(
        select(Incident).options(
            joinedload(Incident.plans),
            joinedload(Incident.report).joinedload(IncidentReport.location_correction),
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


def generate_response_plan(db: Session, incident_id: uuid.UUID,
                           actor_id: uuid.UUID) -> ResponsePlan:
    incident = get_incident(db, incident_id)
    if incident.status not in {"CONFIRMED", "ACTIVE"}:
        raise Conflict("A response plan can only be generated for a confirmed or active incident.")
    extraction = incident.report.extraction
    if extraction is None:
        raise Conflict("This incident has no structured extraction to plan from.")

    facts = dict(extraction.effective_facts)
    actions, requirements = _recommend_actions(facts)
    latest_version = db.scalar(
        select(func.max(ResponsePlan.version)).where(ResponsePlan.incident_id == incident.id)
    ) or 0
    plan = ResponsePlan(
        incident_id=incident.id,
        version=latest_version + 1,
        status="AWAITING_APPROVAL",
        source_facts=facts,
        recommended_actions=actions,
        resource_candidates=[],
        gaps=[
            "No verified department/resource registry is configured; no specific responders are named or assigned.",
            *requirements,
        ],
        human_approval_required=True,
        generated_by=actor_id,
    )
    db.add(plan)
    db.flush()
    _audit(db, actor_id, "RESPONSE_PLAN_GENERATED", incident_id=incident.id,
           plan_id=plan.id, details={"version": plan.version, "status": plan.status,
                                     "source_facts": facts})
    db.commit()
    db.refresh(plan)
    return plan


def decide_response_plan(db: Session, plan_id: uuid.UUID, actor_id: uuid.UUID,
                         decision: str, reason: str | None = None) -> ResponsePlan:
    plan = db.get(ResponsePlan, plan_id)
    if plan is None:
        raise NotFound("Response plan not found.")
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