"""Shared authentication and role dependencies."""
import uuid

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.auth_service import decode_access_token


def get_current_user(
    incident_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    user_id = decode_access_token(incident_session) if incident_session else None
    user = db.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in is required.",
        )
    return user


def get_current_user_id(user: User = Depends(get_current_user)) -> uuid.UUID:
    return user.id


def require_roles(*roles: str):
    def check_role(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="You do not have permission to perform this action.")
        return user

    return check_role
