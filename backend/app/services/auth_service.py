"""Password hashing, signed sessions, and local demo account provisioning."""
import logging
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.user import User

log = logging.getLogger(__name__)
password_hash = PasswordHash.recommended()
_dummy_password_hash = password_hash.hash("invalid-account-password")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    return password_hash.verify(password, stored_hash or _dummy_password_hash)


def create_access_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    if not settings.auth_secret_key:
        raise RuntimeError("AUTH_SECRET_KEY is not configured.")
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.auth_token_expire_minutes)
    return jwt.encode(
        {"sub": str(user_id), "exp": expires_at},
        settings.auth_secret_key,
        algorithm="HS256",
    )


def decode_access_token(token: str) -> uuid.UUID | None:
    settings = get_settings()
    if not settings.auth_secret_key:
        return None
    try:
        payload = jwt.decode(token, settings.auth_secret_key, algorithms=["HS256"])
        return uuid.UUID(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        return None


def seed_demo_accounts(db: Session) -> None:
    """Create/update only accounts explicitly configured in the local environment."""
    settings = get_settings()
    configured = [account for account in settings.demo_accounts if account[1] and account[2]]
    if not configured:
        log.info("No demo accounts configured; provision accounts before enabling login.")
        return
    if not settings.auth_secret_key:
        raise RuntimeError("Set AUTH_SECRET_KEY before configuring demo accounts.")
    if len({email for _, email, _ in configured}) != len(configured):
        raise RuntimeError("Demo account emails must be unique.")

    for role, email, password in configured:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, role=role, password_hash=hash_password(password))
            db.add(user)
        else:
            user.role = role
            user.password_hash = hash_password(password)
            user.is_active = True
    db.commit()