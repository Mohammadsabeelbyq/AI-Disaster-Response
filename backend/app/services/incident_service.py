"""Report review, incident confirmation, and human-supervised response planning."""
import uuid
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import func, select
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
from app.models.resource import RegisteredResource
from app.models.user import User
from app.models.report import IncidentReport, ReportStatus
from app.services import resource_service
from app.services.errors import Conflict, NotFound, ValidationFailed
from app.services.resource_service import (
    _distance_metres,
    _incident_capabilities,
    _normalise_capability,
)
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


def link_report_to_incident(db: Session, incident_id: uuid.UUID, report_id: uuid.UUID,
                            actor_id: uuid.UUID, reason: str) -> Incident:
    incident = get_incident(db, incident_id)
    report = _report_or_404(db, report_id)
    reason_text = reason.strip()
    if not reason_text:
        raise ValidationFailed("A reason is required to link a report.")
    if incident.status not in {"CONFIRMED", "ACTIVE"} or incident.merged_into_id is not None:
        raise Conflict("Reports can only be linked to an active canonical incident.")
    if report.status not in {ReportStatus.SUBMITTED, ReportStatus.UNDER_REVIEW}:
        raise Conflict("Only unconfirmed reports can be linked to an incident.")
    if report.incident is not None or report.incident_links:
        raise Conflict("This report is already associated with an incident.")

    report.status = "LINKED"
    db.add(IncidentReportLink(
        incident_id=incident.id,
        report_id=report.id,
        relationship_type="LINKED_REPORT",
        linked_by=actor_id,
        reason=reason_text,
    ))
    _audit(
        db, actor_id, "REPORT_LINKED_TO_INCIDENT", report_id=report.id,
        incident_id=incident.id,
        details={"relationship_type": "LINKED_REPORT", "reason": reason_text},
    )
    db.commit()
    db.expire_all()
    return get_incident(db, incident.id)


def merge_incident(db: Session, source_incident_id: uuid.UUID,
                   target_incident_id: uuid.UUID, actor_id: uuid.UUID,
                   reason: str) -> Incident:
    reason_text = reason.strip()
    if not reason_text:
        raise ValidationFailed("A reason is required to merge incidents.")
    if source_incident_id == target_incident_id:
        raise Conflict("An incident cannot be merged into itself.")

    source = get_incident(db, source_incident_id)
    target = get_incident(db, target_incident_id)
    if source.status != "CONFIRMED" or source.merged_into_id is not None:
        raise Conflict("Only an unmerged confirmed incident can be merged.")
    if target.status not in {"CONFIRMED", "ACTIVE"} or target.merged_into_id is not None:
        raise Conflict("The target must be an active canonical incident.")
    if source.report_id == target.report_id:
        raise Conflict("Incidents based on the same report cannot be merged.")

    # Preserve each source report and its original incident; only add a canonical relationship.
    db.add(IncidentReportLink(
        incident_id=target.id,
        report_id=source.report_id,
        source_incident_id=source.id,
        relationship_type="MERGED_INCIDENT",
        linked_by=actor_id,
        reason=reason_text,
    ))
    source.status = "MERGED"
    source.merged_into_id = target.id

    # Existing report links follow the resulting canonical incident without rewriting reports.
    source_links = db.scalars(
        select(IncidentReportLink).where(
            IncidentReportLink.incident_id == source.id,
        )
    ).all()
    for link in source_links:
        link.incident_id = target.id
        if link.source_incident_id is None:
            link.source_incident_id = source.id

    _audit(
        db, actor_id, "INCIDENT_MERGED", report_id=source.report_id,
        incident_id=target.id,
        details={
            "source_incident_id": str(source.id),
            "target_incident_id": str(target.id),
            "source_report_id": str(source.report_id),
            "reason": reason_text,
        },
    )
    db.commit()
    db.expire_all()
    return get_incident(db, target.id)


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


def get_assigned_resource_ids(db: Session, exclude_incident_id: uuid.UUID | None = None) -> set[str]:
    """Find resource IDs already assigned to active or approved response plans for other incidents."""
    query = select(ResponsePlan).where(ResponsePlan.status.in_(["APPROVED", "AWAITING_APPROVAL"]))
    if exclude_incident_id is not None:
        query = query.where(ResponsePlan.incident_id != exclude_incident_id)
    active_plans = db.scalars(query).all()
    assigned = set()
    for plan in active_plans:
        for cand in (plan.resource_candidates or []):
            rid = cand.get("id") or cand.get("resource_id")
            if rid:
                assigned.add(str(rid))
        if plan.response_option and isinstance(plan.response_option, dict):
            for res in plan.response_option.get("resources", []):
                rid = res.get("id") or res.get("resource_id")
                if rid:
                    assigned.add(str(rid))
    return assigned


def recheck_resource_availability(
    db: Session,
    candidate_ids: list[uuid.UUID],
    exclude_incident_id: uuid.UUID | None = None,
) -> tuple[list[RegisteredResource], list[uuid.UUID]]:
    """
    Recheck resource availability against the database before finalizing the plan.
    Detects availability changes (status changed from AVAILABLE to UNAVAILABLE/BUSY or assigned elsewhere).
    Returns (available_resources, dropped_ids).
    """
    db.expire_all()
    assigned_ids = get_assigned_resource_ids(db, exclude_incident_id=exclude_incident_id)
    available_resources = []
    dropped_ids = []

    for cid in candidate_ids:
        res = db.get(RegisteredResource, cid)
        if res is None:
            dropped_ids.append(cid)
            continue
        if res.status.upper() != "AVAILABLE" or str(res.id) in assigned_ids:
            dropped_ids.append(cid)
            continue
        available_resources.append(res)

    return available_resources, dropped_ids


def evaluate_grounded_resources(
    db: Session,
    incident: Incident,
) -> tuple[list[tuple[RegisteredResource, int, list[str]]], list[str]]:
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

    report = incident.report
    if report.map_latitude is None or report.map_longitude is None:
        return [], constraints_considered

    report_lat = float(report.map_latitude)
    report_lon = float(report.map_longitude)

    settings = get_settings()
    impact_area = getattr(incident, "impact_area", None)
    if impact_area is not None and impact_area.radius_m:
        search_radius = float(impact_area.radius_m)
    else:
        search_radius = float(settings.resource_search_radius_metres)

    required_capabilities = _incident_capabilities(incident)
    assigned_ids = get_assigned_resource_ids(db, exclude_incident_id=incident.id)

    # Use only resources registered in the database - never invent resources
    all_resources = list(db.scalars(select(RegisteredResource)).all())

    candidates: list[tuple[RegisteredResource, int, list[str]]] = []
    for res in all_resources:
        # Exclude unavailable, already-assigned, inactive, busy, deployed
        if res.status.upper() != "AVAILABLE":
            continue
        if str(res.id) in assigned_ids:
            continue

        # Exclude resources without coordinates or beyond search radius
        if res.latitude is None or res.longitude is None:
            continue
        distance = _distance_metres(report_lat, report_lon, float(res.latitude), float(res.longitude))
        if distance > search_radius:
            continue

        # Exclude resources with incompatible capabilities
        res_caps = {
            _normalise_capability(c)
            for c in (res.capabilities or [])
            if isinstance(c, str) and _normalise_capability(c)
        }
        matching = res_caps & set(required_capabilities)
        if required_capabilities and not matching:
            continue

        candidates.append((res, distance, sorted(matching)))

    candidates.sort(key=lambda item: (-len(item[2]), item[1], item[0].name.casefold()))
    return candidates, constraints_considered


def _build_grounded_response_data(
    finalized_candidates: list[tuple[RegisteredResource, int, list[str]]],
    required_capabilities: list[str],
    search_radius: float,
) -> tuple[list[dict], dict, str, list[dict]]:
    """Build resource_candidates, response_option, rationale, and evidence for FR-28 and FR-29."""
    if finalized_candidates:
        resource_candidates = [
            {
                "id": str(res.id),
                "resource_id": str(res.id),
                "name": res.name,
                "type": res.resource_type or "Unknown",
                "capability": ", ".join(res.capabilities) if res.capabilities else "Unknown",
                "capabilities": res.capabilities,
                "status": res.status,
                "distance_m": dist,
                "latitude": float(res.latitude) if res.latitude is not None else None,
                "longitude": float(res.longitude) if res.longitude is not None else None,
                "matching_capabilities": matching_caps,
            }
            for res, dist, matching_caps in finalized_candidates
        ]

        response_option = {
            "resources": [
                {
                    "resource_id": str(res.id),
                    "name": res.name,
                    "type": res.resource_type or "Unknown",
                    "capability": ", ".join(res.capabilities) if res.capabilities else "Unknown",
                    "capabilities": res.capabilities,
                    "status": res.status.lower(),
                    "distance_m": dist,
                }
                for res, dist, matching_caps in finalized_candidates
            ]
        }

        reasons = [
            f"'{res.name}' (type: {res.resource_type or 'Unknown'}) matches required capabilities ({', '.join(matching_caps)}) "
            f"at distance {dist}m with verified AVAILABLE status"
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
                    f"Resource '{res.name}' exists in registered database (ID: {res.id}).",
                    f"Operational availability verified (status: '{res.status}').",
                    f"Capabilities {res.capabilities} match incident requirements: {matching_caps}.",
                    f"Location verified: coordinates ({float(res.latitude):.4f}, {float(res.longitude):.4f}), distance is {dist} metres from incident (within constraint radius {int(search_radius)} metres).",
                    f"Resource type: {res.resource_type}" if getattr(res, "resource_type", None) else "Resource type: Unknown (not registered in database record).",
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
    # 1. Grounding and Constraints Validation (FR-28)
    candidates, constraints_considered = evaluate_grounded_resources(db, incident)

    # 2. Hook for simulated concurrent status change testing
    if pre_finalize_hook:
        pre_finalize_hook()

    # 3. Final validation: recheck resource availability before finalizing plan
    candidate_ids = [res.id for res, _, _ in candidates]
    available_resources, dropped_ids = recheck_resource_availability(
        db, candidate_ids, exclude_incident_id=incident.id
    )
    available_id_set = {r.id for r in available_resources}
    finalized_candidates = [
        (res, dist, matching) for res, dist, matching in candidates
        if res.id in available_id_set
    ]

    settings = get_settings()
    impact_area = getattr(incident, "impact_area", None)
    search_radius = (
        float(impact_area.radius_m)
        if impact_area is not None and impact_area.radius_m
        else float(settings.resource_search_radius_metres)
    )
    required_capabilities = _incident_capabilities(incident)

    # 4. Rationale and Inspectable Evidence (FR-29)
    resource_candidates, response_option, rationale, evidence = _build_grounded_response_data(
        finalized_candidates, required_capabilities, search_radius
    )

    registry_candidates = resource_service.find_plan_candidates(db, facts)
    legacy_candidate_ids = {candidate["id"] for candidate in resource_candidates}
    registry_candidates = [
        candidate for candidate in registry_candidates
        if candidate["id"] not in legacy_candidate_ids
    ]
    for candidate in registry_candidates:
        matched_capabilities = candidate["matched_capabilities"]
        resource_candidates.append({
            **candidate,
            "resource_id": candidate["id"],
            "type": candidate["resource_type"],
            "capability": ", ".join(matched_capabilities),
            "capabilities": matched_capabilities,
            "status": "AVAILABLE",
            "matching_capabilities": matched_capabilities,
        })
        response_option["resources"].append({
            "resource_id": candidate["id"],
            "name": candidate["name"],
            "type": candidate["resource_type"],
            "capability": ", ".join(matched_capabilities),
            "capabilities": matched_capabilities,
            "status": "available",
        })
        evidence.append({
            "resource_id": candidate["id"],
            "facts": [
                f"Resource '{candidate['name']}' exists in the registered department {candidate['department_name']} (ID: {candidate['id']}).",
                "Operational availability verified (availability: 'AVAILABLE').",
                f"Capabilities match incident requirements: {matched_capabilities}.",
            ],
        })

    if registry_candidates:
        registry_summary = "; ".join(
            f"'{candidate['name']}' from {candidate['department_name']} matches "
            f"{', '.join(candidate['matched_capabilities'])}"
            for candidate in registry_candidates
        )
        if finalized_candidates:
            rationale += f" Department-registered resources also matched: {registry_summary}."
        else:
            rationale = f"Recommended department-registered resources: {registry_summary}."

    if finalized_candidates:
        covered = set()
        for _, _, matching in finalized_candidates:
            covered.update(matching)
        unmet = set(required_capabilities) - covered
        gaps = []
        if unmet:
            gaps.append(f"Unmet incident capability requirements: {', '.join(sorted(unmet))}.")
        gaps.extend(requirements)
    elif registry_candidates:
        gaps = list(requirements)
    else:
        gaps = [
            "No available registered resource was found; no suitable registered resources matched the required capabilities and location constraints, so no specific responders are named or assigned.",
            *requirements,
        ]

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