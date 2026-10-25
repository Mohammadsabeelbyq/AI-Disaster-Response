"""Resource registration and backend-side incident proximity calculations."""
import math
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.config import get_settings
from app.models.incident import Incident
from app.models.resources import (
    Department,
    Resource,
    ResourceAssignment,
    ResourceAvailabilityEvent,
)
from app.schemas.resources import NearbyResourcesOut
from app.services.errors import Conflict, NotFound, ValidationFailed

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


def _point_in_ring(longitude: float, latitude: float, ring: list[list[float]]) -> bool:
    inside = False
    for first, second in zip(ring, ring[1:]):
        x1, y1 = first
        x2, y2 = second
        if (y1 > latitude) != (y2 > latitude):
            crossing_longitude = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude < crossing_longitude:
                inside = not inside
    return inside


def _inside_impact_area(incident: Incident, latitude: float, longitude: float) -> bool:
    area = incident.impact_area
    if area is None or area.geometry_type != "POLYGON" or not area.polygon:
        return True
    rings = area.polygon.get("coordinates", [])
    return bool(rings and _point_in_ring(longitude, latitude, rings[0])
                and not any(_point_in_ring(longitude, latitude, hole) for hole in rings[1:]))


def find_resource_matches(
    db: Session,
    incident: Incident,
    *,
    radius_m: int | None = None,
    capabilities: list[str] | None = None,
    statuses: list[str] | None = None,
) -> tuple[int, list[str], list[tuple[Resource, int, list[str]]]]:
    settings = get_settings()
    area_radius = getattr(incident.impact_area, "radius_m", None)
    search_radius = (
        radius_m if radius_m is not None
        else min(area_radius, settings.resource_search_radius_metres)
        if area_radius is not None
        else settings.resource_search_radius_metres
    )
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
    valid_statuses = {
        "AVAILABLE", "BUSY", "DEPLOYED", "UNAVAILABLE", "ASSIGNED", "INACTIVE", "MAINTENANCE",
    }
    if not selected_statuses or not selected_statuses <= valid_statuses:
        raise ValidationFailed("One or more resource availability states are invalid.")

    active_assignment = select(ResourceAssignment.id).where(
        ResourceAssignment.resource_id == Resource.id,
        ResourceAssignment.released_at.is_(None),
    ).exists()
    candidates = db.scalars(
        select(Resource).join(Resource.department)
        .options(joinedload(Resource.department))
        .where(
            Department.is_active.is_(True),
            Resource.availability.in_(selected_statuses),
            ~active_assignment,
        )
        .order_by(Resource.code)
    ).unique()
    matches: list[tuple[Resource, int, list[str]]] = []
    report_latitude = float(incident.report.map_latitude)
    report_longitude = float(incident.report.map_longitude)
    for resource in candidates:
        if (resource.resource_type is None or resource.latitude is None
            or resource.longitude is None):
            continue
        distance = _distance_metres(
            report_latitude, report_longitude,
            float(resource.latitude), float(resource.longitude))
        if distance > search_radius:
            continue
        if not _inside_impact_area(incident, float(resource.latitude), float(resource.longitude)):
            continue
        resource_capabilities = {
            _normalise_capability(value)
            for value in resource.capabilities
            if isinstance(value, str) and _normalise_capability(value)
        }
        matched = sorted(resource_capabilities.intersection(requested))
        if requested and not matched:
            continue
        matches.append((resource, distance, matched))

    matches.sort(key=lambda match: (-len(match[2]), match[1], match[0].code))
    return search_radius, requested, matches


def find_nearby_resources(db: Session, incident_id: uuid.UUID, radius_m: int | None,
                          capabilities: list[str] | None,
                          statuses: list[str] | None) -> NearbyResourcesOut:
    incident = db.scalar(
        select(Incident).options(
            joinedload(Incident.report),
            joinedload(Incident.impact_area),
        ).where(Incident.id == incident_id)
    )
    if incident is None:
        raise NotFound("Incident not found.")

    search_radius, requested, matches = find_resource_matches(
        db, incident, radius_m=radius_m, capabilities=capabilities, statuses=statuses)

    return NearbyResourcesOut(
        incident_id=incident.id,
        radius_m=search_radius,
        requested_capabilities=requested,
        resources=[
            {
                "id": resource.id,
                "code": resource.code,
                "name": resource.name,
                "resource_type": resource.resource_type,
                "department_id": resource.department_id,
                "department_name": resource.department.name,
                "latitude": float(resource.latitude),
                "longitude": float(resource.longitude),
                "capabilities": resource.capabilities,
                "availability": resource.availability,
                "distance_m": distance,
            }
            for resource, distance, _ in matches
        ],
    )
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
        if department.code == "LEGACY_UNASSIGNED" and is_active:
            raise Conflict("Migrated resources must be assigned to real departments before use.")
        if not is_active and db.scalar(
            select(ResourceAssignment.id)
            .join(Resource, ResourceAssignment.resource_id == Resource.id)
            .where(
                Resource.department_id == department.id,
                ResourceAssignment.released_at.is_(None),
            )
            .limit(1)
        ) is not None:
            raise Conflict("Release active resource assignments before deactivating this department.")
        if is_active and any(
            resource.resource_type is None or resource.latitude is None or resource.longitude is None
            for resource in department.resources
        ):
            raise Conflict("Complete resource type and location before activating this department.")
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
    if db.scalar(
        select(ResourceAssignment.id).where(
            ResourceAssignment.resource_id == resource.id,
            ResourceAssignment.released_at.is_(None),
        )
    ) is not None:
        raise Conflict("Release the active response-plan assignment before editing this resource.")
    if department_id is not None:
        department = db.get(Department, department_id)
        if department is None or not department.is_active:
            raise ValidationFailed("Select an active registered department.")
        resource.department = department
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
    if (resource.latitude is None) != (resource.longitude is None):
        raise ValidationFailed("Resource coordinates must either both be set or both be unknown.")
    if resource.department.is_active and (
        resource.resource_type is None or resource.latitude is None or resource.longitude is None
    ):
        raise ValidationFailed("An active-department resource requires a type and complete location.")
    resource.updated_at = _now()
    db.commit()
    return get_resource(db, resource_id)
def update_availability(db: Session, resource_id: uuid.UUID, actor_id: uuid.UUID, *,
                        availability: str, reason: str) -> Resource:
    resource = db.get(Resource, resource_id)
    if resource is None:
        raise NotFound("Resource not found.")
    if availability == "ASSIGNED":
        raise ValidationFailed("Assign resources through an approved response plan.")
    active_assignment = db.scalar(
        select(ResourceAssignment.id).where(
            ResourceAssignment.resource_id == resource.id,
            ResourceAssignment.released_at.is_(None),
        )
    )
    if active_assignment is not None:
        raise Conflict("Release the active response-plan assignment before changing availability.")
    if not resource.department.is_active:
        raise Conflict("Resources owned by an inactive department cannot be made available.")
    if resource.resource_type is None or resource.latitude is None or resource.longitude is None:
        raise Conflict("Complete resource type and location before changing availability.")
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
