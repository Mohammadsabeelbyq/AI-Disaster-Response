"""Report review, incident confirmation, and human-supervised response planning."""
import uuid
import math
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models.incident import Incident, IncidentPriorityOverride, PriorityRuleConfig, ResponsePlan, WorkflowAudit
from app.models.user import User
from app.models.report import IncidentReport, ReportStatus
from app.services.errors import Conflict, NotFound, ValidationFailed

DEFAULT_PRIORITY_WEIGHTS = {
    "life_safety_risk": 0.35,
    "urgency": 0.25,
    "affected_population": 0.2,
    "hazard_level": 0.12,
    "evidence_confidence": 0.08,
}

DEFAULT_PRIORITY_THRESHOLDS = {
    "CRITICAL": 75,
    "HIGH": 55,
    "MEDIUM": 30,
    "LOW": 0,
}

PRIORITY_BANDS = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


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


def _validate_priority_weights(weights: dict) -> dict[str, float]:
    required = set(DEFAULT_PRIORITY_WEIGHTS)
    if set(weights.keys()) != required:
        raise ValidationFailed("Weights must include exactly: life_safety_risk, urgency, affected_population, hazard_level, evidence_confidence.")
    normalized = {k: float(v) for k, v in weights.items()}
    if any(not math.isfinite(value) or value < 0 for value in normalized.values()):
        raise ValidationFailed("Priority weights must be finite, non-negative numbers.")
    total = sum(normalized.values())
    if total <= 0 or abs(total - 1.0) > 0.01:
        raise ValidationFailed("Priority weights must sum to 1.0.")
    return normalized


def _validate_priority_thresholds(thresholds: dict) -> dict[str, float]:
    required = set(DEFAULT_PRIORITY_THRESHOLDS)
    if set(thresholds.keys()) != required:
        raise ValidationFailed("Thresholds must include exactly: CRITICAL, HIGH, MEDIUM, LOW.")
    values = {band: float(value) for band, value in thresholds.items()}
    if any(not math.isfinite(value) or value < 0 or value > 100 for value in values.values()):
        raise ValidationFailed("Priority thresholds must be finite numbers between 0 and 100.")
    if values["CRITICAL"] < values["HIGH"] or values["HIGH"] < values["MEDIUM"] or values["MEDIUM"] < values["LOW"]:
        raise ValidationFailed("Priority thresholds must be ordered CRITICAL >= HIGH >= MEDIUM >= LOW.")
    return values


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


def get_active_priority_config(db: Session) -> PriorityRuleConfig:
    config = db.scalar(
        select(PriorityRuleConfig).where(PriorityRuleConfig.is_active.is_(True)).order_by(PriorityRuleConfig.created_at.desc())
    )
    if config is not None:
        return config

    default_weights = _validate_priority_weights(DEFAULT_PRIORITY_WEIGHTS)
    default_thresholds = _validate_priority_thresholds(DEFAULT_PRIORITY_THRESHOLDS)
    admin_id = _get_admin_user(db) or uuid.uuid4()
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
    normalized_weights = _validate_priority_weights(weights)
    normalized_thresholds = _validate_priority_thresholds(thresholds)
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


def _average_confidence(confidence: dict | None) -> float:
    if not confidence:
        return 0.0
    values = [float(value) for value in confidence.values() if isinstance(value, (int, float))]
    if not values:
        return 0.0
    return sum(values) / len(values)


def _band_from_score(score: float, thresholds: dict[str, float]) -> str:
    if score >= thresholds.get("CRITICAL", 0):
        return "CRITICAL"
    if score >= thresholds.get("HIGH", 0):
        return "HIGH"
    if score >= thresholds.get("MEDIUM", 0):
        return "MEDIUM"
    return "LOW"


def calculate_priority_for_incident(db: Session, incident: Incident) -> Incident:
    config = get_active_priority_config(db)
    extraction = incident.report.extraction if incident.report else None
    facts = dict(extraction.effective_facts) if extraction else {}

    urgency = str(facts.get("urgency") or "LOW").upper()
    urgency_score = {"CRITICAL": 1.0, "HIGH": 0.75, "MEDIUM": 0.5, "LOW": 0.2}.get(urgency, 0.0)
    life_safety_risk = urgency_score

    affected_population = facts.get("affected_persons")
    affected_population_score = min(1.0, float(affected_population or 0) / 25.0) if affected_population is not None else 0.0

    hazard_list = facts.get("hazards") or []
    hazard_score = min(1.0, float(len(hazard_list)) / 4.0) if hazard_list else 0.0

    evidence_score = _average_confidence(getattr(extraction, "confidence", None) if extraction else None)
    factors = {
        "life_safety_risk": life_safety_risk,
        "urgency": urgency_score,
        "affected_population": affected_population_score,
        "hazard_level": hazard_score,
        "evidence_confidence": evidence_score,
    }

    score = (
        config.weights.get("life_safety_risk", 0.0) * factors["life_safety_risk"]
        + config.weights.get("urgency", 0.0) * factors["urgency"]
        + config.weights.get("affected_population", 0.0) * factors["affected_population"]
        + config.weights.get("hazard_level", 0.0) * factors["hazard_level"]
        + config.weights.get("evidence_confidence", 0.0) * factors["evidence_confidence"]
    ) * 100.0
    score = max(0.0, min(100.0, score))

    incident.priority_score = score
    incident.priority_band = _band_from_score(score, config.thresholds)
    incident.priority_rule_version = config.version
    incident.priority_factors = factors
    incident.priority_calculated_at = datetime.now(timezone.utc)
    if incident.priority_original_score is None:
        incident.priority_original_score = score
    if incident.priority_original_band is None:
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
            joinedload(Incident.plans), joinedload(Incident.report)
        ).order_by(Incident.confirmed_at.desc())
    ).unique())


def get_incident(db: Session, incident_id: uuid.UUID) -> Incident:
    incident = db.scalar(
        select(Incident).options(
            joinedload(Incident.plans), joinedload(Incident.report)
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