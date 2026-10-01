"""Login endpoints using signed, HTTP-only browser sessions."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.services.auth_service import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
SESSION_COOKIE = "incident_session"


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=256)
    role: Literal["USER", "MANAGEMENT", "ADMIN"]

    @field_validator("email", mode="before")
    @classmethod
    def _normalise_email(cls, value):
        return str(value or "").strip().lower()


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    role: str


@router.post("/login", response_model=UserOut)
def login(data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    settings = get_settings()
    if not settings.auth_secret_key:
        raise HTTPException(status_code=503, detail="Authentication is not configured.")
    user = db.scalar(select(User).where(User.email == data.email))
    password_ok = verify_password(data.password, user.password_hash if user else None)
    if user is None or not password_ok or not user.is_active or user.role != data.role:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Email, password, or selected role is incorrect.")
    try:
        token = create_access_token(user.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Authentication is not configured.") from exc
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=settings.auth_token_expire_minutes * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    return UserOut(id=str(user.id), email=user.email, role=user.role)


@router.get("/me", response_model=UserOut)
def current_session(user: User = Depends(get_current_user)):
    return UserOut(id=str(user.id), email=user.email, role=user.role)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    settings = get_settings()
    response.delete_cookie(
        key=SESSION_COOKIE,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )