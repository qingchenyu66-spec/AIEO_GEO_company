from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)


class SmsLoginCodeRequest(BaseModel):
    phone: str = Field(min_length=11, max_length=20)


class SmsLoginRequest(BaseModel):
    phone: str = Field(min_length=11, max_length=20)
    code: str = Field(min_length=4, max_length=4)


class PhoneCodeRequest(BaseModel):
    purpose: str = Field(pattern="^(bind|change_old|change_new|password)$")
    phone: str | None = Field(default=None, max_length=20)


class PhoneBindRequest(BaseModel):
    phone: str = Field(min_length=11, max_length=20)
    code: str = Field(min_length=4, max_length=4)


class PhoneChangeRequest(BaseModel):
    old_code: str = Field(min_length=4, max_length=4)
    new_phone: str = Field(min_length=11, max_length=20)
    new_code: str = Field(min_length=4, max_length=4)


class PhoneLoginEnabledRequest(BaseModel):
    enabled: bool


class IdentitySelectRequest(BaseModel):
    ticket: str
    identity_id: int


class IdentitySwitchRequest(BaseModel):
    identity_id: int


class PasswordResetCodeRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)


class PasswordResetRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    code: str = Field(min_length=4, max_length=4)
    new_password: str = Field(min_length=6, max_length=128)


class ChangePasswordRequest(BaseModel):
    """登录用户用已绑定手机的验证码修改自己的密码."""

    code: str = Field(min_length=4, max_length=4)
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
    tenant_has_logo: bool = False
    tenant_logo_updated_at: str | None = None
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
