from pydantic import BaseModel, EmailStr, Field
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
    query: str = Field(max_length=2000)
    limit: int = 5

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=6000)


class ChatRequest(BaseModel):
    question: str = Field(max_length=2000)
    history: list[ChatMessage] = Field(default=[], max_length=20)

class MemberAdd(BaseModel):
    email: EmailStr
    role: Literal["owner", "member", "viewer"] = "member"


class MemberRoleUpdate(BaseModel):
    role: Literal["owner", "member", "viewer"]