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


def update_resource(db: Session, resource_id: uuid.UUID,
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
