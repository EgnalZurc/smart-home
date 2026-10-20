"""Pydantic models for user input validation.

Centralizes validation rules for user-related operations to prevent
injection attacks and ensure data consistency.
"""

import re
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

# Username: alphanumeric + underscore, 3-32 chars, must start with letter
USERNAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{2,31}$")

# Simple email validation pattern (good enough for most cases)
EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


class CreateUserRequest(BaseModel):
    """Request body for creating a new user."""

    username: Annotated[
        str,
        Field(
            min_length=3,
            max_length=32,
            description="Username (alphanumeric + underscore, starts with letter)",
        ),
    ]
    password: Annotated[
        str,
        Field(
            min_length=8,
            max_length=128,
            description="Password (minimum 8 characters)",
        ),
    ]
    display_name: Annotated[
        str,
        Field(
            default="",
            max_length=64,
            description="Display name (optional)",
        ),
    ]
    email: Annotated[
        str | None,
        Field(
            default=None,
            max_length=254,
            description="Email address (optional, validated format)",
        ),
    ]

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Validate username format: alphanumeric + underscore, starts with letter."""
        v = v.strip().lower()
        if not USERNAME_PATTERN.match(v):
            raise ValueError(
                "Username must be 3-32 characters, start with a letter, "
                "and contain only letters, numbers, and underscores"
            )
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        """Validate email format if provided."""
        if v is None or v == "":
            return None
        v = v.strip().lower()
        if not EMAIL_PATTERN.match(v):
            raise ValueError("Invalid email format")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if len(v) > 128:
            raise ValueError("Password must be at most 128 characters")
        # Check for at least some complexity (not all same char)
        if len(set(v)) < 3:
            raise ValueError("Password must contain at least 3 different characters")
        return v

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: str) -> str:
        """Sanitize display name: strip whitespace."""
        return v.strip() if v else ""


class UpdateUserRequest(BaseModel):
    """Request body for updating user fields."""

    display_name: Annotated[
        str | None,
        Field(
            default=None,
            max_length=64,
            description="Display name",
        ),
    ]
    icon: Annotated[
        str | None,
        Field(
            default=None,
            max_length=256,
            description="Icon URL or emoji",
        ),
    ]
    password: Annotated[
        str | None,
        Field(
            default=None,
            min_length=8,
            max_length=128,
            description="New password (minimum 8 characters)",
        ),
    ]

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str | None) -> str | None:
        """Validate password if provided."""
        if v is None:
            return None
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if len(v) > 128:
            raise ValueError("Password must be at most 128 characters")
        if len(set(v)) < 3:
            raise ValueError("Password must contain at least 3 different characters")
        return v

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: str | None) -> str | None:
        """Sanitize display name if provided."""
        if v is None:
            return None
        return v.strip()

    @field_validator("icon")
    @classmethod
    def validate_icon(cls, v: str | None) -> str | None:
        """Validate icon value (URL or emoji)."""
        if v is None or v == "":
            return None
        v = v.strip()
        # Allow URLs or single emoji/short strings
        if len(v) > 256:
            raise ValueError("Icon must be at most 256 characters")
        return v
