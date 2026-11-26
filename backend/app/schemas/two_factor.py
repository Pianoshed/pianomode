from pydantic import BaseModel, Field


class SetupOut(BaseModel):
    secret: str  # typed into the authenticator app if scanning is not possible
    uri: str  # otpauth:// link (what a QR code would hold)


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class DisableIn(CodeIn):
    password: str = Field(min_length=1, max_length=128)


class RecoveryCodesOut(BaseModel):
    recovery_codes: list[str]
