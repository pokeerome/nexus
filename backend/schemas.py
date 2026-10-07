from pydantic import BaseModel, EmailStr
from typing import Literal


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    workspace_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class SearchRequest(BaseModel):
    query: str
    limit: int = 5

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    question: str
    history: list[ChatMessage] = []

class MemberAdd(BaseModel):
    email: EmailStr
    role: Literal["owner", "member", "viewer"] = "member"


class MemberRoleUpdate(BaseModel):
    role: Literal["owner", "member", "viewer"]