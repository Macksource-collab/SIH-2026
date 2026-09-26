from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class Registration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=12, max_length=72)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("Name cannot be blank.")
        return value.strip()

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value):
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes.")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return str(value).lower()


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=1, max_length=72)


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: Literal["admin", "inspector"] | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Name cannot be blank.")
        return value.strip() if value is not None else None


class InspectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_name: str | None = Field(default=None, max_length=200)
    product_category: str | None = Field(default=None, max_length=120)


class FieldCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    corrected_value: str = Field(min_length=1, max_length=500)

    @field_validator("corrected_value")
    @classmethod
    def clean_corrected_value(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Corrected value cannot be blank.")
        return value
