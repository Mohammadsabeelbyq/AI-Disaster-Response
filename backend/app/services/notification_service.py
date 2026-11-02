"""Notification service for ADM-42: Incident Alerts & Approval Notifications.

Handles creation, deduplication, retrieval, and status updates of user notifications.
Ensures notification errors never break business operations.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.user import User
from app.services.errors import NotFound

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_authorized_coordinators(db: Session) -> list[User]:
    """Retrieve all active users with coordinator/admin privileges."""
    stmt = select(User).where(
        User.role.in_(("MANAGEMENT", "ADMIN")),
        User.is_active.is_(True),
    )
    return list(db.scalars(stmt).all())


def create_notification(
    db: Session,
    recipient_id: uuid.UUID,
    notification_type: str,
    title: str,
    message: str,
    *,
    incident_id: uuid.UUID | None = None,
    response_plan_id: uuid.UUID | None = None,
    assignment_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
) -> Notification | None:
    """Create a single persistent notification with deduplication.

    Does not raise exceptions on database errors to prevent breaking the caller.
    """
    try:
        if dedupe_key:
            existing = db.scalar(
                select(Notification).where(
                    Notification.recipient_id == recipient_id,
                    Notification.dedupe_key == dedupe_key,
                )
            )
            if existing is not None:
                logger.info(
                    "Skipping duplicate notification for recipient %s (key=%s)",
                    recipient_id,
                    dedupe_key,
                )
                return existing

        notification = Notification(
            recipient_id=recipient_id,
            notification_type=notification_type,
            title=title,
            message=message,
            incident_id=incident_id,
            response_plan_id=response_plan_id,
            assignment_id=assignment_id,
            dedupe_key=dedupe_key,
            is_read=False,
            created_at=_now(),
        )
        db.add(notification)
        db.flush()
        return notification
    except Exception as exc:
        logger.error(
            "Failed to create notification (recipient=%s, type=%s): %s",
            recipient_id,
            notification_type,
            exc,
            exc_info=True,
        )
        return None


def notify_coordinators(
    db: Session,
    notification_type: str,
    title: str,
    message: str,
    *,
    incident_id: uuid.UUID | None = None,
    response_plan_id: uuid.UUID | None = None,
    assignment_id: uuid.UUID | None = None,
    dedupe_key_prefix: str | None = None,
) -> list[Notification]:
    """Broadcast an operational notification to all active coordinators and admins."""
    created = []
    try:
        coordinators = get_authorized_coordinators(db)
        for user in coordinators:
            dedupe_key = f"{dedupe_key_prefix}:{user.id}" if dedupe_key_prefix else None
            notif = create_notification(
                db,
                recipient_id=user.id,
                notification_type=notification_type,
                title=title,
                message=message,
                incident_id=incident_id,
                response_plan_id=response_plan_id,
                assignment_id=assignment_id,
                dedupe_key=dedupe_key,
            )
            if notif:
                created.append(notif)
    except Exception as exc:
        logger.error("Failed to broadcast notifications to coordinators: %s", exc, exc_info=True)
    return created


# --- High-level Event Dispatchers ---


def notify_new_incident(db: Session, incident) -> list[Notification]:
    """Triggered when an incident is confirmed/created."""
    try:
        disaster = incident.report.disaster_type.replace("_", " ").title() if incident.report else "Incident"
        location = (incident.report.map_location_name or incident.report.location_name or "Unknown location") if incident.report else "Unknown location"
        return notify_coordinators(
            db,
            notification_type="NEW_INCIDENT",
            title=f"New Incident: {disaster}",
            message=f"A new incident (#{str(incident.id)[:8]}) has been confirmed at {location}.",
            incident_id=incident.id,
            dedupe_key_prefix=f"new_incident:{incident.id}",
        )
    except Exception as exc:
        logger.error("Error dispatching new incident notification: %s", exc, exc_info=True)
        return []


def notify_incident_status_changed(
    db: Session, incident, old_status: str, new_status: str, reason: str | None = None
) -> list[Notification]:
    """Triggered when an incident is closed, reopened, or status changes."""
    try:
        extra = f" Reason: {reason}." if reason else ""
        return notify_coordinators(
            db,
            notification_type="INCIDENT_STATUS_CHANGED",
            title=f"Incident Status: {new_status}",
            message=f"Incident #{str(incident.id)[:8]} status changed from {old_status} to {new_status}.{extra}",
            incident_id=incident.id,
            dedupe_key_prefix=f"status_change:{incident.id}:{new_status}",
        )
    except Exception as exc:
        logger.error("Error dispatching incident status notification: %s", exc, exc_info=True)
        return []


def notify_incident_priority_changed(
    db: Session, incident, old_band: str | None, new_band: str, is_override: bool = False, reason: str | None = None
) -> list[Notification]:
    """Triggered when incident priority score or band changes."""
    try:
        action = "overridden" if is_override else "updated"
        extra = f" Reason: {reason}." if reason else ""
        return notify_coordinators(
            db,
            notification_type="INCIDENT_PRIORITY_CHANGED",
            title=f"Incident Priority {action.title()}: {new_band}",
            message=f"Incident #{str(incident.id)[:8]} priority was {action} to {new_band} (was {old_band or 'UNRATED'}).{extra}",
            incident_id=incident.id,
            dedupe_key_prefix=f"priority_change:{incident.id}:{new_band}:{incident.priority_score}",
        )
    except Exception as exc:
        logger.error("Error dispatching incident priority notification: %s", exc, exc_info=True)
        return []


def notify_plan_awaiting_approval(db: Session, plan) -> list[Notification]:
    """Triggered when an advisory response plan requires coordinator approval."""
    try:
        return notify_coordinators(
            db,
            notification_type="PLAN_AWAITING_APPROVAL",
            title=f"Response Plan Awaiting Approval (v{plan.version})",
            message=f"Response plan v{plan.version} for Incident #{str(plan.incident_id)[:8]} has been generated and requires coordinator review.",
            incident_id=plan.incident_id,
            response_plan_id=plan.id,
            dedupe_key_prefix=f"plan_awaiting_approval:{plan.id}:v{plan.version}",
        )
    except Exception as exc:
        logger.error("Error dispatching plan awaiting approval notification: %s", exc, exc_info=True)
        return []


def notify_plan_decided(
    db: Session, plan, decision: str, reason: str | None = None
) -> list[Notification]:
    """Triggered when a plan is approved or rejected."""
    try:
        extra = f" Reason: {reason}." if reason else ""
        notif_type = "PLAN_APPROVED" if decision.upper() == "APPROVED" else "PLAN_REJECTED"
        return notify_coordinators(
            db,
            notification_type=notif_type,
            title=f"Response Plan {decision.title()} (v{plan.version})",
            message=f"Response plan v{plan.version} for Incident #{str(plan.incident_id)[:8]} was {decision.lower()}.{extra}",
            incident_id=plan.incident_id,
            response_plan_id=plan.id,
            dedupe_key_prefix=f"plan_decided:{plan.id}:{decision.upper()}",
        )
    except Exception as exc:
        logger.error("Error dispatching plan decision notification: %s", exc, exc_info=True)
        return []


def notify_assignment_confirmed(
    db: Session, assignment, resource_label: str | None = None
) -> list[Notification]:
    """Triggered AFTER a resource assignment is confirmed in the database."""
    try:
        label = resource_label or str(assignment.resource_id)[:8]
        return notify_coordinators(
            db,
            notification_type="ASSIGNMENT_CONFIRMED",
            title="Resource Assignment Confirmed",
            message=f"Resource '{label}' was successfully assigned to Incident #{str(assignment.incident_id)[:8]}.",
            incident_id=assignment.incident_id,
            response_plan_id=assignment.plan_id,
            assignment_id=assignment.id,
            dedupe_key_prefix=f"assignment_confirmed:{assignment.id}",
        )
    except Exception as exc:
        logger.error("Error dispatching assignment confirmed notification: %s", exc, exc_info=True)
        return []


def notify_operation_failed(
    db: Session,
    operation_name: str,
    error_message: str,
    *,
    incident_id: uuid.UUID | None = None,
    plan_id: uuid.UUID | None = None,
) -> list[Notification]:
    """Triggered when an approval or assignment operation fails and requires attention."""
    try:
        # Minute-based dedupe to avoid spamming identical failures
        time_tag = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
        return notify_coordinators(
            db,
            notification_type="OPERATION_FAILED",
            title=f"Operation Failed: {operation_name}",
            message=f"An operation failed and requires coordinator attention: {error_message}",
            incident_id=incident_id,
            response_plan_id=plan_id,
            dedupe_key_prefix=f"op_failed:{operation_name}:{incident_id}:{plan_id}:{time_tag}",
        )
    except Exception as exc:
        logger.error("Error dispatching operation failure notification: %s", exc, exc_info=True)
        return []


# --- Queries & Status Management ---


def get_user_notifications(
    db: Session,
    user_id: uuid.UUID,
    *,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[Notification]:
    """Retrieve notifications strictly for the authenticated recipient."""
    stmt = (
        select(Notification)
        .where(Notification.recipient_id == user_id)
        .order_by(Notification.created_at.desc())
    )
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))

    stmt = stmt.limit(min(max(limit, 1), 100)).offset(max(offset, 0))
    return list(db.scalars(stmt).all())


def get_unread_count(db: Session, user_id: uuid.UUID) -> int:
    """Count unread notifications for the authenticated user."""
    stmt = select(func.count(Notification.id)).where(
        Notification.recipient_id == user_id,
        Notification.is_read.is_(False),
    )
    return db.scalar(stmt) or 0


def mark_as_read(db: Session, notification_id: uuid.UUID, user_id: uuid.UUID) -> Notification:
    """Mark a specific notification as read, ensuring it belongs to the authenticated user."""
    notification = db.get(Notification, notification_id)
    if notification is None or notification.recipient_id != user_id:
        raise NotFound("Notification not found.")

    if not notification.is_read:
        notification.is_read = True
        db.commit()
        db.refresh(notification)
    return notification


def mark_all_as_read(db: Session, user_id: uuid.UUID) -> int:
    """Mark all unread notifications for the authenticated user as read."""
    stmt = (
        update(Notification)
        .where(
            Notification.recipient_id == user_id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    result = db.execute(stmt)
    db.commit()
    return result.rowcount or 0
