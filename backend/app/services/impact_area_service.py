"""Persistence operations for incident-linked impact areas."""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.impact_area import ImpactArea
from app.services.incident_service import get_incident
from app.schemas.impact_area import ImpactAreaCreate


def get_impact_area(db: Session, incident_id: uuid.UUID) -> ImpactArea | None:
    get_incident(db, incident_id)
    return db.scalar(select(ImpactArea).where(ImpactArea.incident_id == incident_id))


def save_impact_area(db: Session, incident_id: uuid.UUID, actor_id: uuid.UUID,
                     data: ImpactAreaCreate) -> ImpactArea:
    incident = get_incident(db, incident_id)
    area = db.scalar(select(ImpactArea).where(ImpactArea.incident_id == incident.id))
    if area is None:
        area = ImpactArea(incident_id=incident.id)
        db.add(area)
    area.geometry_type = data.geometry_type
    area.radius_m = data.radius_m
    area.polygon = data.polygon.model_dump(mode="json") if data.polygon else None
    area.updated_by = actor_id
    db.commit()
    db.refresh(area)
    return area
