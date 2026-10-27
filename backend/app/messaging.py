from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlencode

RISKLENS_ENV = os.getenv("RISKLENS_ENV", "development").strip().lower()
SMTP_HOST = os.getenv("RISKLENS_SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("RISKLENS_SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("RISKLENS_SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("RISKLENS_SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("RISKLENS_EMAIL_FROM", "").strip()
PUBLIC_APP_URL = os.getenv("RISKLENS_PUBLIC_APP_URL", "http://localhost:5173").rstrip("/")
logger = logging.getLogger("risklens.security-mail")

if RISKLENS_ENV == "production":
    missing = [
        name for name, value in (
            ("RISKLENS_SMTP_HOST", SMTP_HOST),
            ("RISKLENS_EMAIL_FROM", EMAIL_FROM),
            ("RISKLENS_PUBLIC_APP_URL", PUBLIC_APP_URL),
        ) if not value
    ]
    if missing:
        raise RuntimeError(
            "Production account recovery/invitations require: " + ", ".join(missing)
        )
    if not PUBLIC_APP_URL.startswith("https://"):
        raise RuntimeError("RISKLENS_PUBLIC_APP_URL must use HTTPS in production")


def create_action_url(action: str, token: str) -> str:
    if action not in {"reset_token", "invite_token"}:
        raise ValueError("Unsupported security email action")
    return f"{PUBLIC_APP_URL}/?{urlencode({action: token})}"


def send_security_email(recipient: str, subject: str, body: str) -> None:
    """Send via configured SMTP; development logs links for local testing only."""
    if not SMTP_HOST or not EMAIL_FROM:
        if RISKLENS_ENV == "production":
            raise RuntimeError("SMTP delivery is not configured")
        logger.warning("Local-only account email for %s: %s", recipient, body)
        return

    message = EmailMessage()
    message["From"] = EMAIL_FROM
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    context = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
        server.starttls(context=context)
        if SMTP_USERNAME:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(message)
