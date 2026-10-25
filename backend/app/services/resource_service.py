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
