"""Resource registration and backend-side incident proximity calculations."""
import math
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.incident import Incident
from app.models.resource import RegisteredResource
from app.schemas.resource import NearbyResourcesOut, ResourceCreate
from app.services.errors import NotFound, ValidationFailed

EARTH_MEAN_RADIUS_METRES = 6_371_008.8
CAPABILITY_ALIASES = {
    "MEDICAL_EMERGENCY": {"MEDICAL", "MEDICAL_AID", "MEDICAL_SUPPORT"},
    "ROAD_ACCIDENT": {"RESCUE", "MEDICAL", "MEDICAL_AID"},
    "BUILDING_COLLAPSE": {"RESCUE", "SEARCH_AND_RESCUE"},
    "LANDSLIDE": {"RESCUE", "SEARCH_AND_RESCUE"},
    "FLOOD": {"RESCUE", "WATER_RESCUE"},
    "FIRE": {"FIRE_SUPPRESSION", "FIRE"},
    "CYCLONE": {"RESCUE", "SHELTER"},
}


def _normalise_capability(value: str) -> str:
    return re.sub(r"[^A-Z0-9_-]", "", value.strip().upper().replace(" ", "_"))


def _incident_capabilities(incident: Incident) -> list[str]:
    extraction = incident.report.extraction
    facts = extraction.effective_facts if extraction is not None else {}
    capabilities = {
        _normalise_capability(value)
        for field in ("requested_assistance", "hazards")
        for value in facts.get(field, [])
        if isinstance(value, str) and _normalise_capability(value)
    }
    disaster_type = incident.report.disaster_type
    capabilities.update(CAPABILITY_ALIASES.get(disaster_type, set()))
    return sorted(capabilities)


def _distance_metres(latitude_a: float, longitude_a: float,
                     latitude_b: float, longitude_b: float) -> int:
    lat_a, lat_b = math.radians(latitude_a), math.radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(longitude_b - longitude_a)
    haversine = (math.sin(delta_lat / 2) ** 2
                 + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2)
    return round(2 * EARTH_MEAN_RADIUS_METRES * math.asin(math.sqrt(min(1, haversine))))


def register_resource(db: Session, actor_id: uuid.UUID, data: ResourceCreate) -> RegisteredResource:
    resource = RegisteredResource(created_by=actor_id, **data.model_dump())
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return resource


def update_registered_resource(db: Session, resource_id: uuid.UUID,
                               data: ResourceCreate) -> RegisteredResource:
    resource = db.get(RegisteredResource, resource_id)
    if resource is None:
        raise NotFound("Resource not found.")
    for field, value in data.model_dump().items():
        setattr(resource, field, value)
    db.commit()
    db.refresh(resource)
    return resource


def find_nearby_resources(db: Session, incident_id: uuid.UUID, radius_m: int | None,
                          capabilities: list[str] | None,
                          statuses: list[str] | None) -> NearbyResourcesOut:
    incident = db.scalar(select(Incident).where(Incident.id == incident_id))
    if incident is None:
        raise NotFound("Incident not found.")

    settings = get_settings()
    search_radius = radius_m if radius_m is not None else settings.resource_search_radius_metres
    if search_radius <= 0 or search_radius > settings.resource_max_search_radius_metres:
        raise ValidationFailed(
            f"radius_m must be between 1 and {settings.resource_max_search_radius_metres}.")

    requested = sorted({
        _normalise_capability(capability)
        for capability in (capabilities if capabilities is not None
                           else _incident_capabilities(incident))
        if _normalise_capability(capability)
    })
    selected_statuses = set(statuses or ["AVAILABLE"])
    valid_statuses = {"AVAILABLE", "BUSY", "DEPLOYED", "UNAVAILABLE"}
    if not selected_statuses or not selected_statuses <= valid_statuses:
        raise ValidationFailed("status must be one or more of AVAILABLE, BUSY, DEPLOYED, UNAVAILABLE.")

    report = incident.report
    candidates = db.scalars(
        select(RegisteredResource).where(RegisteredResource.status.in_(selected_statuses))
    ).all()
    results = []
    for resource in candidates:
        if resource.latitude is None or resource.longitude is None:
            continue
        distance = _distance_metres(
            float(report.latitude), float(report.longitude),
            float(resource.latitude), float(resource.longitude))
        if distance > search_radius:
            continue
        matching_capabilities = set(resource.capabilities) & set(requested)
        if not matching_capabilities:
            continue
        results.append((resource, distance, len(matching_capabilities)))

    results.sort(key=lambda match: (-match[2], match[1], match[0].name.casefold()))
    return NearbyResourcesOut(
        incident_id=incident.id,
        radius_m=search_radius,
        requested_capabilities=requested,
        resources=[
            {
                "id": resource.id,
                "name": resource.name,
                "latitude": float(resource.latitude),
                "longitude": float(resource.longitude),
                "capabilities": resource.capabilities,
                "status": resource.status,
                "distance_m": distance,
            }
            for resource, distance, _ in results
        ],
    )
"""Persistent department/resource registry and audited availability workflows."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.resources import Department, Resource, ResourceAvailabilityEvent
from app.services.errors import Conflict, NotFound, ValidationFailed


def _now() -> datetime:
    return datetime.now(timezone.utc)


def list_departments(db: Session, *, active_only: bool = False) -> list[Department]:
    query = select(Department).order_by(Department.name, Department.code)
    if active_only:
        query = query.where(Department.is_active.is_(True))
    return list(db.scalars(query).all())


def create_department(db: Session, actor_id: uuid.UUID, *, code: str, name: str,
                      department_type: str) -> Department:
    department = Department(
        code=code,
        name=name,
        department_type=department_type,
        created_by=actor_id,
    )
    db.add(department)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(f"Department code '{code}' is already registered.") from exc
    db.refresh(department)
    return department


def update_department(db: Session, department_id: uuid.UUID, *,
                      name: str | None = None, department_type: str | None = None,
                      is_active: bool | None = None) -> Department:
    department = db.get(Department, department_id)
    if department is None:
        raise NotFound("Department not found.")
    if name is not None:
        department.name = name
    if department_type is not None:
        department.department_type = department_type
    if is_active is not None:
        if not is_active and any(
            resource.availability == "AVAILABLE" for resource in department.resources
        ):
            raise Conflict("Set registered resources unavailable before deactivating this department.")
        department.is_active = is_active
    department.updated_at = _now()
    db.commit()
    db.refresh(department)
    return department


def list_resources(db: Session, *, department_id: uuid.UUID | None = None,
                   availability: str | None = None) -> list[Resource]:
    query = select(Resource).options(
        joinedload(Resource.department),
        selectinload(Resource.availability_events),
    ).order_by(Resource.code)
    if department_id is not None:
        query = query.where(Resource.department_id == department_id)
    if availability is not None:
        query = query.where(Resource.availability == availability)
    return list(db.scalars(query).unique())


def get_resource(db: Session, resource_id: uuid.UUID) -> Resource:
    resource = db.scalar(
        select(Resource).options(
            joinedload(Resource.department),
            selectinload(Resource.availability_events),
        ).where(Resource.id == resource_id)
    )
    if resource is None:
        raise NotFound("Resource not found.")
    return resource


def create_resource(db: Session, actor_id: uuid.UUID, *, code: str, department_id: uuid.UUID,
                    resource_type: str, name: str, capabilities: list[str],
                    latitude: float, longitude: float, availability: str) -> Resource:
    department = db.get(Department, department_id)
    if department is None or not department.is_active:
        raise ValidationFailed("Select an active registered department.")
    resource = Resource(
        code=code,
        department_id=department_id,
        resource_type=resource_type,
        name=name,
        capabilities=capabilities,
        latitude=latitude,
        longitude=longitude,
        availability=availability,
        created_by=actor_id,
    )
    db.add(resource)
    try:
        db.flush()
        db.add(ResourceAvailabilityEvent(
            resource_id=resource.id,
            changed_by=actor_id,
            previous_availability=None,
            new_availability=availability,
            reason="Initial availability recorded when the resource was registered.",
        ))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict(f"Resource code '{code}' is already registered.") from exc
    return get_resource(db, resource.id)


def update_resource(db: Session, resource_id: uuid.UUID, *,
                    department_id: uuid.UUID | None = None,
                    resource_type: str | None = None,
                    name: str | None = None,
                    capabilities: list[str] | None = None,
                    latitude: float | None = None,
                    longitude: float | None = None) -> Resource:
    resource = db.get(Resource, resource_id)
    if resource is None:
        raise NotFound("Resource not found.")
    if department_id is not None:
        department = db.get(Department, department_id)
        if department is None or not department.is_active:
            raise ValidationFailed("Select an active registered department.")
        resource.department_id = department_id
    if resource_type is not None:
        resource.resource_type = resource_type
    if name is not None:
        resource.name = name
    if capabilities is not None:
        resource.capabilities = capabilities
    if latitude is not None:
        resource.latitude = latitude
    if longitude is not None:
        resource.longitude = longitude
    resource.updated_at = _now()
    db.commit()
    return get_resource(db, resource_id)


def update_availability(db: Session, resource_id: uuid.UUID, actor_id: uuid.UUID, *,
                        availability: str, reason: str) -> Resource:
    resource = db.get(Resource, resource_id)
    if resource is None:
        raise NotFound("Resource not found.")
    if not resource.department.is_active:
        raise Conflict("Resources owned by an inactive department cannot be made available.")
    if resource.availability == availability:
        raise Conflict("Resource already has this availability state.")

    previous = resource.availability
    resource.availability = availability
    resource.updated_at = _now()
    db.add(ResourceAvailabilityEvent(
        resource_id=resource.id,
        changed_by=actor_id,
        previous_availability=previous,
        new_availability=availability,
        reason=reason,
    ))
    db.commit()
    return get_resource(db, resource_id)


def find_plan_candidates(db: Session, facts: dict) -> list[dict]:
    requested = {
        value.strip().upper()
        for value in facts.get("requested_assistance", [])
        if isinstance(value, str) and value.strip()
    }
    if not requested:
        return []

    resources = db.scalars(
        select(Resource).join(Resource.department).options(joinedload(Resource.department))
        .where(
            Resource.availability == "AVAILABLE",
            Department.is_active.is_(True),
        )
        .order_by(Resource.code)
    ).unique()
    candidates = []
    for resource in resources:
        matched = sorted(requested.intersection(
            capability.strip().upper()
            for capability in resource.capabilities
            if isinstance(capability, str)
        ))
        if matched:
            candidates.append({
                "id": str(resource.id),
                "code": resource.code,
                "name": resource.name,
                "resource_type": resource.resource_type,
                "department_code": resource.department.code,
                "department_name": resource.department.name,
                "matched_capabilities": matched,
            })
    return candidates
