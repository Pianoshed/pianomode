from pydantic import BaseModel, EmailStr, Field


class DeleteAccountIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    confirm: str = Field(description='Must be the word "DELETE"')
    otp: str | None = Field(default=None, max_length=32)  # needed when two-factor is on


class ChangeEmailIn(BaseModel):
    new_email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ConfirmEmailChangeIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
