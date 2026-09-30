"""Shared API dependencies.

get_current_user_id is a PLACEHOLDER. When the auth/RBAC module (JWT) lands, make this return
the authenticated user's UUID (and enforce USER/MANAGEMENT/ADMIN as the design requires).
Reports are stored with submitted_by=None until then."""
import uuid


def get_current_user_id() -> uuid.UUID | None:
    return None
