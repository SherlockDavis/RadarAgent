from __future__ import annotations

from pydantic import BaseModel


class UserCreate(BaseModel):
    email: str
    password: str
    output_language: str = "zh"


class User(BaseModel):
    id: int
    email: str
    output_language: str = "zh"
    is_admin: bool = False
    created_at: str
