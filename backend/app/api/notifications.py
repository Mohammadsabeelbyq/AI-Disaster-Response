"""API endpoints for coordinator and user notifications (ADM-42)."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.notification import MarkReadOut, NotificationOut, UnreadCountOut
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_user_notifications(
    unread_only: bool = Query(False, description="Filter for unread notifications only"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Retrieve private notifications for the authenticated user."""
    return notification_service.get_user_notifications(
        db, user.id, unread_only=unread_only, limit=limit, offset=offset
    )


@router.get("/unread-count", response_model=UnreadCountOut)
def get_unread_notification_count(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Retrieve the number of unread notifications for the authenticated user."""
    count = notification_service.get_unread_count(db, user.id)
    return {"unread_count": count}


@router.patch("/{notification_id}/read", response_model=NotificationOut)
def mark_notification_as_read(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark a specific notification as read. Verifies recipient matches the authenticated user."""
    return notification_service.mark_as_read(db, notification_id, user.id)


@router.patch("/read-all", response_model=MarkReadOut)
def mark_all_notifications_as_read(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark all unread notifications for the authenticated user as read."""
    updated = notification_service.mark_all_as_read(db, user.id)
    return {"updated_count": updated}
