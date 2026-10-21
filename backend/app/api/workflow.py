"""Management-owned report review and human-supervised response planning APIs."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.database import get_db
from app.models.user import User
from app.schemas.impact_area import ImpactAreaCreate, ImpactAreaOut
from app.schemas.resource import NearbyResourcesOut
from app.schemas.report import (
    IncidentOut,
    PriorityConfigInput,
    PriorityConfigOut,
    PriorityOverrideInput,
    PlanDecision,
    ReportDismissal,
    ReportOut,
    ResponsePlanOut,
)
from app.services import incident_service
from app.services import impact_area_service, resource_service

management_user = Depends(require_roles("MANAGEMENT", "ADMIN"))
reports_router = APIRouter(tags=["incident-workflow"])
incidents_router = APIRouter(prefix="/incidents", tags=["incident-workflow"])
plans_router = APIRouter(prefix="/response-plans", tags=["response-plans"])
priority_router = APIRouter(tags=["priority-policy"])


@reports_router.post("/reports/{report_id}/review", response_model=ReportOut)
def start_report_review(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = management_user,
):
    return incident_service.start_report_review(db, report_id, user.id)


@reports_router.post("/reports/{report_id}/confirm", response_model=IncidentOut, status_code=201)
def confirm_report(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = management_user,
):
    return incident_service.confirm_report(db, report_id, user.id)


@reports_router.post("/reports/{report_id}/dismiss", response_model=ReportOut)
def dismiss_report(
    report_id: uuid.UUID,
    decision: ReportDismissal,
    db: Session = Depends(get_db),
    user: User = management_user,
):
    return incident_service.dismiss_report(db, report_id, user.id, decision.reason)


@incidents_router.get("", response_model=list[IncidentOut])
def list_incidents(db: Session = Depends(get_db), user: User = management_user):
    return incident_service.list_incidents(db)


@incidents_router.get("/{incident_id}", response_model=IncidentOut)
def get_incident(incident_id: uuid.UUID, db: Session = Depends(get_db),
                 user: User = management_user):
    return incident_service.get_incident(db, incident_id)


@incidents_router.get("/{incident_id}/impact-area", response_model=ImpactAreaOut | None)
def get_impact_area(
    incident_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = management_user,
):
    return impact_area_service.get_impact_area(db, incident_id)


@incidents_router.put("/{incident_id}/impact-area", response_model=ImpactAreaOut)
def save_impact_area(
    incident_id: uuid.UUID,
    data: ImpactAreaCreate,
    db: Session = Depends(get_db),
    user: User = management_user,
):
    return impact_area_service.save_impact_area(db, incident_id, user.id, data)


@incidents_router.get("/{incident_id}/resources", response_model=NearbyResourcesOut)
def find_incident_resources(
    incident_id: uuid.UUID,
    radius_m: int | None = Query(default=None),
    capability: list[str] | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = management_user,
):
    return resource_service.find_nearby_resources(
        db, incident_id, radius_m, capability, status
    )


@incidents_router.get("/{incident_id}/priority", response_model=IncidentOut)
def get_incident_priority(incident_id: uuid.UUID, db: Session = Depends(get_db),
                         user: User = management_user):
    incident = incident_service.get_incident(db, incident_id)
    if incident.priority_calculated_at is None:
        incident_service.calculate_priority_for_incident(db, incident)
        db.commit()
        db.refresh(incident)
    return incident


@incidents_router.post("/{incident_id}/priority/override", response_model=IncidentOut)
def override_incident_priority(incident_id: uuid.UUID, payload: PriorityOverrideInput,
                              db: Session = Depends(get_db), user: User = management_user):
    return incident_service.override_incident_priority(
        db,
        incident_id,
        user.id,
        reason=payload.reason,
        score=payload.score,
        band=payload.band,
    )


@priority_router.get("/priority-configs", response_model=list[PriorityConfigOut])
def list_priority_configs(db: Session = Depends(get_db), user: User = Depends(require_roles("ADMIN"))):
    return incident_service.list_priority_configs(db)


@priority_router.get("/priority-configs/active", response_model=PriorityConfigOut)
def get_active_priority_config(db: Session = Depends(get_db), user: User = Depends(require_roles("ADMIN"))):
    return incident_service.get_active_priority_config(db)


@priority_router.post("/priority-configs", response_model=PriorityConfigOut, status_code=201)
def create_priority_config(payload: PriorityConfigInput,
                          db: Session = Depends(get_db),
                          user: User = Depends(require_roles("ADMIN"))):
    return incident_service.create_priority_configuration(
        db,
        user.id,
        weights=payload.weights,
        thresholds=payload.thresholds,
        notes=payload.notes,
    )


@incidents_router.get("/{incident_id}/recommendations")
def get_incident_recommendations(
    incident_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = management_user,
):
    incident = incident_service.get_incident(db, incident_id)
    candidates, constraints_considered = incident_service.evaluate_grounded_resources(db, incident)
    candidate_ids = [res.id for res, _, _ in candidates]
    available_resources, _ = incident_service.recheck_resource_availability(
        db, candidate_ids, exclude_incident_id=incident.id
    )
    available_id_set = {r.id for r in available_resources}
    finalized = [(r, d, m) for r, d, m in candidates if r.id in available_id_set]

    settings = incident_service.get_settings()
    impact_area = getattr(incident, "impact_area", None)
    search_radius = (
        float(impact_area.radius_m)
        if impact_area is not None and impact_area.radius_m
        else float(settings.resource_search_radius_metres)
    )
    required_capabilities = incident_service._incident_capabilities(incident)

    resource_candidates, response_option, rationale, evidence = incident_service._build_grounded_response_data(
        finalized, required_capabilities, search_radius
    )

    return {
        "incident_id": incident.id,
        "response_option": response_option,
        "constraints_considered": constraints_considered,
        "rationale": rationale,
        "evidence": evidence,
    }


@incidents_router.post("/{incident_id}/plans", response_model=ResponsePlanOut, status_code=201)
def generate_response_plan(incident_id: uuid.UUID, db: Session = Depends(get_db),
                           user: User = management_user):
    return incident_service.generate_response_plan(db, incident_id, user.id)


@plans_router.get("/{plan_id}", response_model=ResponsePlanOut)
def get_response_plan(plan_id: uuid.UUID, db: Session = Depends(get_db),
                      user: User = management_user):
    return incident_service.get_response_plan(db, plan_id)


@plans_router.post("/{plan_id}/approve", response_model=ResponsePlanOut)
def approve_response_plan(plan_id: uuid.UUID, decision: PlanDecision,
                          db: Session = Depends(get_db), user: User = management_user):
    return incident_service.decide_response_plan(
        db, plan_id, user.id, "APPROVED", decision.reason)


@plans_router.post("/{plan_id}/reject", response_model=ResponsePlanOut)
def reject_response_plan(plan_id: uuid.UUID, decision: PlanDecision,
                         db: Session = Depends(get_db), user: User = management_user):
    return incident_service.decide_response_plan(
        db, plan_id, user.id, "REJECTED", decision.reason)