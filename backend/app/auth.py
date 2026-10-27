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
from backend.app.models import UserRecord, UserSessionRecord
from backend.app.tenancy import DEFAULT_TENANT_ID, ensure_default_tenant

JWT_ALGORITHM = "HS256"
RISKLENS_ENV = os.getenv("RISKLENS_ENV", "development").strip().lower()
_DEVELOPMENT_JWT_SECRET = "local-development-secret-change-this-before-deploy-2026"

if RISKLENS_ENV not in {"development", "test", "production"}:
    raise RuntimeError("RISKLENS_ENV must be development, test, or production")

_configured_secret = os.getenv("RISKLENS_JWT_SECRET", "").strip()
if RISKLENS_ENV == "production" and not _configured_secret:
    raise RuntimeError("RISKLENS_JWT_SECRET is required when RISKLENS_ENV=production")

JWT_SECRET = _configured_secret or _DEVELOPMENT_JWT_SECRET
if len(JWT_SECRET) < 32:
    raise RuntimeError("RISKLENS_JWT_SECRET must contain at least 32 characters")
if RISKLENS_ENV == "production" and JWT_SECRET == _DEVELOPMENT_JWT_SECRET:
    raise RuntimeError("The built-in development JWT secret cannot be used in production")
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


def create_access_token(
    subject: str,
    db: Session,
    tenant_id: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ACCESS_TOKEN_MINUTES)
    session_id = str(uuid4())
    db.add(UserSessionRecord(
        id=session_id,
        user_id=subject,
        tenant_id=tenant_id,
        created_at=now,
        expires_at=expires_at,
        ip_address=(ip_address or "")[:64] or None,
        user_agent=(user_agent or "")[:255] or None,
    ))
    db.commit()
    return jwt.encode(
        {
            "sub": subject,
            "jti": session_id,
            "iat": now,
            "nbf": now,
            "exp": expires_at,
            "iss": "risklens-ai",
            "aud": "risklens-api",
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def get_current_session(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> UserSessionRecord:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid, expired, or revoked access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            issuer="risklens-ai",
            audience="risklens-api",
            options={"require": ["sub", "jti", "iat", "nbf", "exp", "iss", "aud"]},
        )
    except jwt.InvalidTokenError:
        raise unauthorized from None

    subject = payload.get("sub")
    session_id = payload.get("jti")
    if not isinstance(subject, str) or not subject or not isinstance(session_id, str):
        raise unauthorized
    session = db.get(UserSessionRecord, session_id)
    if session is None or session.user_id != subject or session.revoked_at is not None:
        raise unauthorized
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise unauthorized
    user = db.get(UserRecord, subject)
    if (
        user is None
        or not user.is_active
        or user.tenant_id != session.tenant_id
    ):
        raise unauthorized
    return session


def get_current_user(
    session: UserSessionRecord = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> UserRecord:
    user = db.get(UserRecord, session.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
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
    ensure_default_tenant(db)
    existing = db.scalar(select(UserRecord).where(UserRecord.email == email))
    if existing is not None:
        if (
            existing.role != "admin"
            or existing.tenant_id != DEFAULT_TENANT_ID
            or not existing.is_active
        ):
            raise RuntimeError(
                "Bootstrap email is already used by a non-default workspace, "
                "a non-admin role, or a disabled account. Choose a clean admin "
                "email; bootstrap never changes an existing account."
            )
        return
    db.add(UserRecord(
        id=str(uuid4()),
        tenant_id=DEFAULT_TENANT_ID,
        email=email,
        password_hash=hash_password(password),
        role="admin",
        is_active=True,
    ))
    db.commit()
