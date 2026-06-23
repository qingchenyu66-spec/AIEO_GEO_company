from pydantic import BaseModel, Field


class MenuInfo(BaseModel):
    """返回给前端的菜单与动作权限。"""

    id: int
    menu_code: str
    menu_name: str
    identity_type: str
    route_path: str
    icon: str
    sort_order: int
    can_create: bool = False
    can_update: bool = False
    can_delete: bool = False
    can_export: bool = True


class RoleInfo(BaseModel):
    """角色下拉选项。"""

    id: int
    role_code: str
    role_name: str
    identity_type: str
    data_scope: str


class UserIdentityCreateItem(BaseModel):
    """新增用户时某一个登录身份的角色、企业和菜单权限。"""

    identity_type: str = Field(pattern="^(PLATFORM|CUSTOMER)$")
    role_code: str = Field(min_length=2, max_length=50)
    identity_name: str = Field(min_length=2, max_length=80)
    tenant_id: int | None = None
    tenant_name: str | None = Field(default=None, max_length=100)
    menu_ids: list[int] = Field(default_factory=list)


class UserCreateRequest(BaseModel):
    """平台端新增用户时提交的账号和多个登录身份。"""

    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(min_length=2, max_length=50)
    identities: list[UserIdentityCreateItem] = Field(min_length=1)


class UserUpdateRequest(BaseModel):
    """平台端维护用户资料和权限。"""

    display_name: str = Field(min_length=2, max_length=50)
    identities: list[UserIdentityCreateItem] = Field(min_length=1)


class PasswordResetRequest(BaseModel):
    """管理员重置用户密码。"""

    password: str = Field(min_length=6, max_length=128)


class TenantCreateRequest(BaseModel):
    """平台端新增企业。"""

    name: str = Field(min_length=2, max_length=100)
    code: str | None = Field(default=None, max_length=50)


class ManagedUserInfo(BaseModel):
    """用户管理列表展示数据。"""

    id: int
    username: str
    display_name: str
    status: bool
    created_by: int | None
    identities: list[dict]
