from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)


class IdentitySelectRequest(BaseModel):
    ticket: str
    identity_id: int


class IdentitySwitchRequest(BaseModel):
    identity_id: int


class ChangePasswordRequest(BaseModel):
    """登录用户修改自己的密码（强制改密 / 自助改密共用）。"""

    old_password: str = Field(min_length=6, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class IdentityInfo(BaseModel):
    id: int
    identity_type: str
    identity_name: str
    role_code: str
    position_id: int | None = None
    position_name: str | None = None
    position_code: str | None = None
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
    # 2026-07-30 - 平台范围多选 - 有 models 编辑权时生效；空=不可勾任何端
    allowed_monitor_platforms: list[str] = []
