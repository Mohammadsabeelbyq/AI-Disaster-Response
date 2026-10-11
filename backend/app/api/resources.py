"""Administrator-managed resource registry APIs."""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.database import get_db
from app.models.user import User
from app.schemas.resource import ResourceCreate, ResourceOut
from app.services import resource_service

router = APIRouter(prefix="/resources", tags=["resources"])


@router.post("", response_model=ResourceOut, status_code=201)
def register_resource(data: ResourceCreate, db: Session = Depends(get_db),
                      user: User = Depends(require_roles("ADMIN"))):
    return resource_service.register_resource(db, user.id, data)


@router.put("/{resource_id}", response_model=ResourceOut,
            dependencies=[Depends(require_roles("ADMIN"))])
def update_resource(resource_id: uuid.UUID, data: ResourceCreate,
                    db: Session = Depends(get_db)):
    return resource_service.update_resource(db, resource_id, data)
