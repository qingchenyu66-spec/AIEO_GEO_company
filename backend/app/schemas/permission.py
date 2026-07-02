from datetime import date

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


class MenuGrantItem(BaseModel):
    """职位/身份的单项菜单动作权限。"""

    menu_id: int
    menu_code: str | None = None
    can_create: bool = False
    can_update: bool = False
    can_delete: bool = False
    can_export: bool = False


class MenuConfigUpdateRequest(BaseModel):
    menu_name: str | None = Field(default=None, min_length=1, max_length=120)
    sort_order: int | None = Field(default=None, ge=0, le=10000)
    is_visible: bool | None = None
    icon: str | None = Field(default=None, max_length=50)
    route_path: str | None = Field(default=None, max_length=255)
    remark: str | None = Field(default=None, max_length=500)


class MenuConfigBatchItem(BaseModel):
    id: int = Field(gt=0)
    menu_name: str | None = Field(default=None, min_length=1, max_length=120)
    sort_order: int | None = Field(default=None, ge=0, le=10000)
    is_visible: bool | None = None


class RoleInfo(BaseModel):
    """角色下拉选项。"""

    id: int
    role_code: str
    role_name: str
    identity_type: str
    data_scope: str


class PositionInfo(BaseModel):
    id: int
    position_code: str
    position_name: str
    identity_type: str
    role_code: str
    description: str | None = None
    menu_ids: list[int] = Field(default_factory=list)
    menu_grants: list[MenuGrantItem] = Field(default_factory=list)


class PositionSaveRequest(BaseModel):
    position_name: str = Field(min_length=2, max_length=80)
    identity_type: str = Field(pattern="^(PLATFORM|CUSTOMER)$")
    role_code: str = Field(min_length=2, max_length=50)
    description: str | None = Field(default=None, max_length=255)
    menu_ids: list[int] = Field(default_factory=list)
    menu_grants: list[MenuGrantItem] = Field(default_factory=list)
    status: bool = True


class UserIdentityCreateItem(BaseModel):
    """新增用户时某一个登录身份的角色、企业和菜单权限。"""

    identity_type: str = Field(pattern="^(PLATFORM|CUSTOMER)$")
    role_code: str = Field(min_length=2, max_length=50)
    identity_name: str | None = Field(default=None, max_length=80)
    position_id: int | None = None
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
    service_start_date: date | None = None
    service_end_date: date | None = None


class TenantUpdateRequest(BaseModel):
    """平台端维护企业服务期限和启停状态。"""

    name: str = Field(min_length=2, max_length=100)
    code: str | None = Field(default=None, max_length=50)
    service_start_date: date | None = None
    service_end_date: date | None = None
    status: bool = True


class ManagedUserInfo(BaseModel):
    """用户管理列表展示数据。"""

    id: int
    username: str
    display_name: str
    status: bool
    created_by: int | None
    identities: list[dict]
