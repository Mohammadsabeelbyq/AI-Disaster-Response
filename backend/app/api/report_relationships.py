"""Coordinator APIs for detecting and reviewing potential report relationships."""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.database import get_db
from app.models.user import User
from app.schemas.report_relationship import RelationshipDecision, ReportRelationshipOut
from app.services import report_relationship_service

router = APIRouter(
    tags=["report-relationships"],
    dependencies=[Depends(get_current_user)],
)
coordinator = Depends(require_roles("MANAGEMENT", "ADMIN"))


@router.post(
    "/reports/{report_id}/potential-relationships",
    response_model=list[ReportRelationshipOut],
)
def detect_report_relationships(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = coordinator,
):
    proposals = report_relationship_service.detect_potential_relationships(
        db, report_id, user.id
    )
    return [
        report_relationship_service.relationship_output(db, proposal)
        for proposal in proposals
    ]


@router.get("/report-relationships", response_model=list[ReportRelationshipOut])
def get_report_relationships(
    status: Literal["PROPOSED", "CONFIRMED", "REJECTED"] = Query(default="PROPOSED"),
    db: Session = Depends(get_db),
    user: User = coordinator,
):
    return report_relationship_service.list_relationships(db, status)


@router.post(
    "/report-relationships/{relationship_id}/confirm",
    response_model=ReportRelationshipOut,
)
def confirm_report_relationship(
    relationship_id: uuid.UUID,
    decision: RelationshipDecision,
    db: Session = Depends(get_db),
    user: User = coordinator,
):
    return report_relationship_service.decide_relationship(
        db, relationship_id, user.id, "CONFIRMED", decision.reason
    )


@router.post(
    "/report-relationships/{relationship_id}/reject",
    response_model=ReportRelationshipOut,
)
def reject_report_relationship(
    relationship_id: uuid.UUID,
    decision: RelationshipDecision,
    db: Session = Depends(get_db),
    user: User = coordinator,
):
    return report_relationship_service.decide_relationship(
        db, relationship_id, user.id, "REJECTED", decision.reason
    )
