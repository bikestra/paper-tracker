"""Authentication utilities."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets

from fastapi import Cookie, Depends, Request
from sqlalchemy.orm import Session

from . import crud, models
from .db import get_db

logger = logging.getLogger(__name__)

# App password from environment
APP_PASSWORD = os.getenv("APP_PASSWORD", "")

# Secret key for signing session tokens
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
if not SESSION_SECRET:
    logger.warning(
        "SESSION_SECRET not set - generating random secret (sessions won't persist across restarts)"
    )
    SESSION_SECRET = secrets.token_hex(32)

# Cookie name
SESSION_COOKIE = "paper_tracker_session"


class NotAuthenticatedException(Exception):
    """Raised when user is not authenticated."""

    pass


def _create_session_token() -> str:
    """Create a session token."""
    return hashlib.sha256(f"{SESSION_SECRET}:authenticated".encode()).hexdigest()


def _verify_session_token(token: str) -> bool:
    """Verify a session token."""
    expected = _create_session_token()
    return secrets.compare_digest(token, expected)


def verify_password(password: str) -> bool:
    """Verify the app password."""
    if not APP_PASSWORD:
        # No password set - allow access (for local dev)
        return True
    return secrets.compare_digest(password, APP_PASSWORD)


def is_authenticated(session: str | None) -> bool:
    """Check if session token is valid."""
    if not APP_PASSWORD:
        # No password configured - allow all access
        return True
    if session and _verify_session_token(session):
        return True
    return False


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    session: str | None = Cookie(None, alias=SESSION_COOKIE),
) -> models.User:
    """Get the current authenticated user.

    Raises NotAuthenticatedException if not authenticated.
    """
    if not is_authenticated(session):
        logger.info(
            f"User not authenticated (session={'present' if session else 'missing'})"
        )
        raise NotAuthenticatedException()

    # For password auth, use default user (single-user mode)
    user = crud.get_user_by_id(db, crud.DEFAULT_USER_ID)
    if user:
        logger.debug(f"Found user id={user.id}")
        return user

    # Create default user if doesn't exist
    logger.warning(
        f"Default user (id={crud.DEFAULT_USER_ID}) not found, creating new user"
    )
    new_user = crud.get_or_create_user_by_email(db, "user@paper-tracker.local")
    logger.warning(
        f"Created/found user with id={new_user.id} - papers may not be visible if they belong to a different user"
    )
    return new_user
