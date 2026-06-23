from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)


class IdentitySelectRequest(BaseModel):
    ticket: str
    identity_id: int


class IdentitySwitchRequest(BaseModel):
    identity_id: int


class IdentityInfo(BaseModel):
    id: int
    identity_type: str
    identity_name: str
    role_code: str
    tenant_id: int | None
    tenant_name: str | None
    is_default: bool


class AuthSession(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict
    identity: IdentityInfo
    identities: list[IdentityInfo]
    menus: list[dict] = []
