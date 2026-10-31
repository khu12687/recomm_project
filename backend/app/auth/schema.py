from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)


class EmailRequest(BaseModel):
    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        if isinstance(value, str):
            return value.strip().lower()
        return value


class SignupRequest(EmailRequest):
    password: str = Field(min_length=8, max_length=128)


class VerifyEmailRequest(EmailRequest):
    code: str = Field(pattern=r"^[0-9]{6}$")


class LoginRequest(EmailRequest):
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    is_verified: bool
    created_at: datetime


class CodeResponse(BaseModel):
    message: str
    server_time: datetime
    expires_at: datetime
    resend_available_at: datetime
    attempts_remaining: int


class MessageResponse(BaseModel):
    message: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int