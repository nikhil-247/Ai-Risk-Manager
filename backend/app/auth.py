from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import UserRecord

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("RISKLENS_ACCESS_TOKEN_MINUTES", "30"))
_DEVELOPMENT_SECRET = "local-development-secret-change-this-before-deploying-2026"
_secret = os.getenv("RISKLENS_JWT_SECRET_KEY")
_environment = os.getenv("RISKLENS_ENV", "development").lower()
if not _secret and _environment == "production":
    raise RuntimeError("RISKLENS_JWT_SECRET_KEY must be configured in production")
JWT_SECRET_KEY = _secret or _DEVELOPMENT_SECRET
if len(JWT_SECRET_KEY) < 32:
    raise RuntimeError("RISKLENS_JWT_SECRET_KEY must contain at least 32 characters")

password_hasher = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        return password_hasher.verify(password, encoded_hash)
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> UserRecord:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "iat", "sub", "type"]},
        )
        if payload.get("type") != "access":
            raise unauthorized
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized

    user = db.get(UserRecord, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


def require_roles(*roles: str) -> Callable:
    allowed_roles = frozenset(roles)

    def dependency(user: UserRecord = Depends(get_current_user)) -> UserRecord:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role does not have permission to perform this action",
            )
        return user

    return dependency


def user_payload(user: UserRecord) -> dict[str, object]:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def bootstrap_admin(db: Session) -> None:
    email = os.getenv("RISKLENS_BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("RISKLENS_BOOTSTRAP_ADMIN_PASSWORD", "")
    if not email and not password:
        return
    if not email or not password:
        raise RuntimeError(
            "Set both RISKLENS_BOOTSTRAP_ADMIN_EMAIL and RISKLENS_BOOTSTRAP_ADMIN_PASSWORD, or neither"
        )
    if len(password) < 12:
        raise RuntimeError("RISKLENS_BOOTSTRAP_ADMIN_PASSWORD must be at least 12 characters")
    existing = db.query(UserRecord).filter(UserRecord.email == email).first()
    if existing is None:
        db.add(
            UserRecord(
                email=email,
                password_hash=hash_password(password),
                role="admin",
                is_active=True,
            )
        )
        db.commit()
