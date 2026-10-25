"""Legacy resource and department-backed registry APIs."""
import uuid

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.database import get_db
from app.models.user import User
from app.schemas.resource import ResourceCreate as LegacyResourceCreate
from app.schemas.resource import ResourceOut as LegacyResourceOut
from app.schemas.resources import (
    DepartmentCreate,
    DepartmentOut,
    DepartmentUpdate,
    ResourceAvailabilityUpdate,
    ResourceCreate as RegistryResourceCreate,
    ResourceOut as RegistryResourceOut,
    ResourceUpdate,
)
from app.services import resource_service

router = APIRouter(tags=["resource-registry"])
coordinator = Depends(require_roles("MANAGEMENT", "ADMIN"))
administrator = Depends(require_roles("ADMIN"))


@router.post("/resources", response_model=RegistryResourceOut | LegacyResourceOut,
             status_code=201)
def create_resource(
    payload: Annotated[RegistryResourceCreate | LegacyResourceCreate, Body()],
    db: Session = Depends(get_db),
    user: User = administrator,
):
    if isinstance(payload, LegacyResourceCreate):
        return resource_service.register_resource(db, user.id, payload)
    return resource_service.create_resource(db, user.id, **payload.model_dump())


@router.put("/resources/{resource_id}", response_model=LegacyResourceOut,
            dependencies=[Depends(require_roles("ADMIN"))])
def update_registered_resource(resource_id: uuid.UUID, data: LegacyResourceCreate,
                               db: Session = Depends(get_db)):
    return resource_service.update_registered_resource(db, resource_id, data)


@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(active_only: bool = False, db: Session = Depends(get_db),
                     user: User = coordinator):
    return resource_service.list_departments(db, active_only=active_only)


@router.post("/departments", response_model=DepartmentOut, status_code=201)
def create_department(payload: DepartmentCreate, db: Session = Depends(get_db),
                      user: User = administrator):
    return resource_service.create_department(
        db, user.id, code=payload.code, name=payload.name,
        department_type=payload.department_type)


@router.patch("/departments/{department_id}", response_model=DepartmentOut)
def update_department(department_id: uuid.UUID, payload: DepartmentUpdate,
                      db: Session = Depends(get_db), user: User = administrator):
    return resource_service.update_department(
        db, department_id, **payload.model_dump(exclude_unset=True))


@router.get("/resources", response_model=list[RegistryResourceOut])
def list_resources(
    department_id: uuid.UUID | None = None,
    availability: str | None = Query(default=None, pattern=r"^(AVAILABLE|UNAVAILABLE|MAINTENANCE)$"),
    db: Session = Depends(get_db),
    user: User = coordinator,
):
    return resource_service.list_resources(
        db, department_id=department_id, availability=availability)


@router.get("/resources/{resource_id}", response_model=RegistryResourceOut)
def get_resource(resource_id: uuid.UUID, db: Session = Depends(get_db),
                 user: User = coordinator):
    return resource_service.get_resource(db, resource_id)


@router.patch("/resources/{resource_id}", response_model=RegistryResourceOut)
def update_resource(resource_id: uuid.UUID, payload: ResourceUpdate,
                    db: Session = Depends(get_db), user: User = administrator):
    return resource_service.update_resource(
        db, resource_id, **payload.model_dump(exclude_unset=True))


@router.patch("/resources/{resource_id}/availability", response_model=RegistryResourceOut)
def update_resource_availability(resource_id: uuid.UUID,
                                 payload: ResourceAvailabilityUpdate,
                                 db: Session = Depends(get_db),
                                 user: User = coordinator):
    return resource_service.update_availability(
        db, resource_id, user.id, availability=payload.availability,
        reason=payload.reason)


@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(active_only: bool = False, db: Session = Depends(get_db),
                     user: User = coordinator):
    return resource_service.list_departments(db, active_only=active_only)


@router.post("/departments", response_model=DepartmentOut, status_code=201)
def create_department(payload: DepartmentCreate, db: Session = Depends(get_db),
                      user: User = administrator):
    return resource_service.create_department(
        db, user.id, code=payload.code, name=payload.name,
        department_type=payload.department_type)


@router.patch("/departments/{department_id}", response_model=DepartmentOut)
def update_department(department_id: uuid.UUID, payload: DepartmentUpdate,
                      db: Session = Depends(get_db), user: User = administrator):
    return resource_service.update_department(
        db, department_id, **payload.model_dump(exclude_unset=True))
