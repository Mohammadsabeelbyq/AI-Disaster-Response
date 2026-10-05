"""Report review, incident confirmation, and human-supervised response planning."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models.incident import Incident, ResponsePlan, WorkflowAudit
from app.models.report import IncidentReport, ReportStatus
from app.services.errors import Conflict, NotFound


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
        select(Incident).options(joinedload(Incident.plans)).order_by(Incident.confirmed_at.desc())
    ).unique())


def get_incident(db: Session, incident_id: uuid.UUID) -> Incident:
    incident = db.scalar(
        select(Incident).options(joinedload(Incident.plans)).where(Incident.id == incident_id)
    )
    if incident is None:
        raise NotFound("Incident not found.")
    return incident


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