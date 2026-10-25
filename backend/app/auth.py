from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import UserRecord

JWT_ALGORITHM = "HS256"
JWT_SECRET = os.getenv(
    "RISKLENS_JWT_SECRET",
    "local-development-secret-change-this-before-deploy-2026",
)
if len(JWT_SECRET) < 32:
    raise RuntimeError("RISKLENS_JWT_SECRET must contain at least 32 characters")
ACCESS_TOKEN_MINUTES = int(os.getenv("RISKLENS_ACCESS_TOKEN_MINUTES", "30"))
if not 5 <= ACCESS_TOKEN_MINUTES <= 1440:
    raise RuntimeError("RISKLENS_ACCESS_TOKEN_MINUTES must be between 5 and 1440")

_password_hasher = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password, password_hash)
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": subject, "iat": now, "exp": now + timedelta(minutes=ACCESS_TOKEN_MINUTES)},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


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
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            raise unauthorized
    except jwt.InvalidTokenError:
        raise unauthorized from None

    user = db.get(UserRecord, subject)
    if user is None or not user.is_active:
        raise unauthorized
    return user


def require_roles(*roles: str) -> Callable:
    allowed = frozenset(roles)

    def role_dependency(user: UserRecord = Depends(get_current_user)) -> UserRecord:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account role does not permit this action",
            )
        return user

    return role_dependency


def bootstrap_admin(db: Session) -> None:
    """Create the first admin only when both bootstrap environment values are configured."""
    email = normalize_email(os.getenv("RISKLENS_BOOTSTRAP_ADMIN_EMAIL", ""))
    password = os.getenv("RISKLENS_BOOTSTRAP_ADMIN_PASSWORD", "")
    if not email and not password:
        return
    if not email or not password:
        raise RuntimeError(
            "Set both RISKLENS_BOOTSTRAP_ADMIN_EMAIL and "
            "RISKLENS_BOOTSTRAP_ADMIN_PASSWORD, or leave both unset"
        )
    if len(password) < 12:
        raise RuntimeError("Bootstrap admin password must be at least 12 characters")
    if email.count("@") != 1 or "." not in email.rsplit("@", 1)[-1]:
        raise RuntimeError("RISKLENS_BOOTSTRAP_ADMIN_EMAIL must be a valid email address")
    existing = db.scalar(select(UserRecord).where(UserRecord.email == email))
    if existing is not None:
        return
    db.add(UserRecord(
        id=str(uuid4()), email=email, password_hash=hash_password(password),
        role="admin", is_active=True,
    ))
    db.commit()
