import uuid
from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.models.user import Role

DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Password = Annotated[str, Field(min_length=1, max_length=256)]  # strength is checked in the service
Token = Annotated[str, Field(min_length=10, max_length=200)]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Password
    display_name: DisplayName


class LoginRequest(BaseModel):
    """`identifier` is an email, or a login ID for institution seats. `email` is still accepted."""

    model_config = ConfigDict(populate_by_name=True)

    identifier: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=320)
    ] = Field(validation_alias=AliasChoices("identifier", "email"))
    password: Password
    # Two-factor code (or a recovery code), once the account has two-factor sign-in on.
    otp: Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)] | None = None


class VerifyEmailRequest(BaseModel):
    token: Token


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: Token
    new_password: Password


class ChangePasswordRequest(BaseModel):
    current_password: Password
    new_password: Password


class UpdateProfileRequest(BaseModel):
    display_name: DisplayName


class UpdatePreferencesRequest(BaseModel):
    reminder_emails: bool


class DeactivateRequest(BaseModel):
    password: Password


class MessageResponse(BaseModel):
    message: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str | None
    login_id: str | None = None
    display_name: str
    roles: list[Role]
    email_verified: bool
    reminder_emails: bool = True
    two_factor_enabled: bool = False
    # An administrator on a site that requires two-factor, who has not turned it on yet.
    two_factor_setup_needed: bool = False
    institution_role: Literal["owner", "seat"] | None = None
