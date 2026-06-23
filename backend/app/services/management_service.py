from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload
import hashlib

from app.core.security import hash_password
from app.models.permission import Role, UserIdentityMenu
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.schemas.permission import UserCreateRequest, UserIdentityCreateItem, UserUpdateRequest
from app.services.permission_service import default_menu_ids_for_role, replace_identity_menus


def can_manage_all_users(identity: UserIdentity) -> bool:
    """平台超级管理员可查看全部用户，其余人员只看自己创建的用户。"""
    return identity.identity_type == "PLATFORM" and identity.role_code == "PLATFORM_ADMIN"


def list_managed_users(
    db: Session,
    current_user: User,
    current_identity: UserIdentity,
    *,
    keyword: str | None = None,
    tenant_id: int | None = None,
    identity_type: str | None = None,
    status: bool | None = None,
    deleted: bool = False,
) -> list[User]:
    """用户列表数据隔离和筛选：管理员看全部，普通管理人员只看自己创建的账号。"""
    stmt = (
        select(User)
        .options(joinedload(User.identities).joinedload(UserIdentity.tenant))
        .where(User.deleted.is_(deleted))
        .order_by(User.id.desc())
    )
    if not can_manage_all_users(current_identity):
        stmt = stmt.where(User.created_by == current_user.id)
    if status is not None:
        stmt = stmt.where(User.status.is_(status))
    if keyword and keyword.strip():
        like_value = f"%{keyword.strip()}%"
        stmt = stmt.where(
            or_(
                User.username.like(like_value),
                User.display_name.like(like_value),
                User.identities.any(UserIdentity.identity_name.like(like_value)),
            )
        )
    if tenant_id is not None:
        stmt = stmt.where(User.identities.any(UserIdentity.tenant_id == tenant_id))
    if identity_type:
        stmt = stmt.where(User.identities.any(UserIdentity.identity_type == identity_type))
    return list(db.scalars(stmt).unique())


def get_managed_user(
    db: Session,
    user_id: int,
    current_user: User,
    current_identity: UserIdentity,
    *,
    include_deleted: bool = False,
) -> User:
    """读取单个可管理用户，并复用创建人数据隔离规则。"""
    conditions = [User.id == user_id]
    if not include_deleted:
        conditions.append(User.deleted.is_(False))
    user = db.scalar(
        select(User)
        .options(joinedload(User.identities).joinedload(UserIdentity.tenant))
        .where(*conditions)
    )
    if user is None:
        raise ValueError("用户不存在")
    if not can_manage_all_users(current_identity) and user.created_by != current_user.id:
        raise ValueError("无权管理该用户")
    return user


def _tenant_code_from_name(name: str) -> str:
    """根据企业名称生成一个稳定的演示编码，正式项目可替换为统一社会信用代码。"""
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()[:10].upper()
    return f"TENANT_{digest}"


def _reject_garbled_text(value: str | None, field_name: str) -> None:
    """拒绝明显已经乱码的输入，避免把问号脏数据写进数据库。"""
    if value and value.strip() and set(value.strip()) == {"?"}:
        raise ValueError(f"{field_name}疑似编码异常，请重新输入中文后保存")


def _resolve_tenant(db: Session, item: UserIdentityCreateItem) -> Tenant | None:
    """客户企业身份需要企业；可选择已有企业，也可输入新企业名称并自动创建。"""
    if item.identity_type != "CUSTOMER":
        return None
    if item.tenant_id is not None:
        tenant = db.scalar(select(Tenant).where(Tenant.id == item.tenant_id, Tenant.status.is_(True), Tenant.deleted.is_(False)))
        if tenant is None:
            raise ValueError("所属企业不存在或已停用")
        return tenant
    if not item.tenant_name or not item.tenant_name.strip():
        raise ValueError("客户企业端账号必须选择或输入所属企业")
    tenant_name = item.tenant_name.strip()
    _reject_garbled_text(tenant_name, "企业名称")
    tenant = db.scalar(select(Tenant).where(Tenant.name == tenant_name, Tenant.deleted.is_(False)))
    if tenant is None:
        tenant = Tenant(name=tenant_name, code=_tenant_code_from_name(tenant_name))
        db.add(tenant)
        db.flush()
    return tenant


def _create_identity_for_user(db: Session, user: User, item: UserIdentityCreateItem, *, is_default: bool) -> None:
    """给用户创建一个登录身份，并写入该身份的菜单权限。"""
    _reject_garbled_text(item.identity_name, "身份名称")
    role = db.scalar(select(Role).where(Role.role_code == item.role_code, Role.identity_type == item.identity_type, Role.status.is_(True), Role.deleted.is_(False)))
    if role is None:
        raise ValueError(f"{item.identity_name} 的角色不存在或已停用")

    tenant = _resolve_tenant(db, item)
    identity = UserIdentity(
        identity_code=f"{item.identity_type}_{user.id}_{item.role_code}",
        user_id=user.id,
        tenant_id=tenant.id if tenant else None,
        identity_type=item.identity_type,
        identity_name=item.identity_name,
        role_code=item.role_code,
        is_default=is_default,
    )
    db.add(identity)
    db.flush()

    menu_ids = item.menu_ids or default_menu_ids_for_role(db, item.role_code)
    replace_identity_menus(db, identity.id, menu_ids, writable=item.identity_type == "PLATFORM")


def _upsert_identity_for_user(db: Session, user: User, item: UserIdentityCreateItem, *, is_default: bool) -> None:
    """更新或创建某个身份，并重写菜单权限。"""
    _reject_garbled_text(item.identity_name, "身份名称")
    role = db.scalar(select(Role).where(Role.role_code == item.role_code, Role.identity_type == item.identity_type, Role.status.is_(True), Role.deleted.is_(False)))
    if role is None:
        raise ValueError(f"{item.identity_name} 的角色不存在或已停用")
    tenant = _resolve_tenant(db, item)
    identity = db.scalar(
        select(UserIdentity).where(
            UserIdentity.user_id == user.id,
            UserIdentity.identity_type == item.identity_type,
            UserIdentity.deleted.is_(False),
        )
    )
    if identity is None:
        identity = UserIdentity(
            identity_code=f"{item.identity_type}_{user.id}_{item.role_code}",
            user_id=user.id,
            identity_type=item.identity_type,
        )
        db.add(identity)
    identity.tenant_id = tenant.id if tenant else None
    identity.identity_name = item.identity_name
    identity.role_code = item.role_code
    identity.is_default = is_default
    identity.status = True
    identity.deleted = False
    db.flush()
    replace_identity_menus(db, identity.id, item.menu_ids or default_menu_ids_for_role(db, item.role_code), writable=item.identity_type == "PLATFORM")


def create_managed_user(db: Session, payload: UserCreateRequest, creator: User, creator_identity: UserIdentity) -> User:
    """创建账号、多个登录身份和菜单权限。

    注意：这里允许一个人同时拥有平台运营端和客户企业端身份，登录后再选择进入哪个工作区。
    """
    exists = db.scalar(select(User).where(User.username == payload.username, User.deleted.is_(False)))
    if exists is not None:
        raise ValueError("账号已存在")
    _reject_garbled_text(payload.display_name, "用户姓名")

    # 普通平台人员创建的账号只归自己可见；平台管理员依然可以看到全部。
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        created_by=creator.id,
    )
    db.add(user)
    db.flush()

    identity_types = [item.identity_type for item in payload.identities]
    if len(identity_types) != len(set(identity_types)):
        raise ValueError("同一用户不能重复添加相同登录身份")
    for index, item in enumerate(payload.identities):
        _create_identity_for_user(db, user, item, is_default=index == 0)

    db.commit()
    db.refresh(user)
    return user


def update_managed_user(db: Session, user_id: int, payload: UserUpdateRequest, current_user: User, current_identity: UserIdentity) -> User:
    """修改用户资料、身份配置和菜单权限。"""
    user = get_managed_user(db, user_id, current_user, current_identity)
    _reject_garbled_text(payload.display_name, "用户姓名")
    identity_types = [item.identity_type for item in payload.identities]
    if len(identity_types) != len(set(identity_types)):
        raise ValueError("同一用户不能重复添加相同登录身份")

    user.display_name = payload.display_name
    keep_types = set(identity_types)
    for identity in user.identities:
        if identity.identity_type not in keep_types:
            identity.deleted = True
            identity.status = False
            db.query(UserIdentityMenu).filter(UserIdentityMenu.identity_id == identity.id).delete(synchronize_session=False)
    for index, item in enumerate(payload.identities):
        _upsert_identity_for_user(db, user, item, is_default=index == 0)
    db.commit()
    db.refresh(user)
    return user


def reset_managed_user_password(db: Session, user_id: int, password: str, current_user: User, current_identity: UserIdentity) -> None:
    """管理员重置指定用户密码。"""
    user = get_managed_user(db, user_id, current_user, current_identity)
    user.password_hash = hash_password(password)
    db.commit()


def set_managed_user_status(db: Session, user_id: int, enabled: bool, current_user: User, current_identity: UserIdentity) -> User:
    """启用或禁用账号。禁用后该账号无法登录。"""
    user = get_managed_user(db, user_id, current_user, current_identity)
    if user.id == current_user.id and not enabled:
        raise ValueError("不能禁用当前登录账号")
    user.status = enabled
    for identity in user.identities:
        identity.status = enabled
    db.commit()
    db.refresh(user)
    return user


def delete_managed_user(db: Session, user_id: int, current_user: User, current_identity: UserIdentity) -> User:
    """逻辑删除账号：保留历史数据和权限配置，默认列表不再展示。"""
    user = get_managed_user(db, user_id, current_user, current_identity)
    if user.id == current_user.id:
        raise ValueError("不能删除当前登录账号")
    user.deleted = True
    user.status = False
    for identity in user.identities:
        identity.deleted = True
        identity.status = False
    db.commit()
    db.refresh(user)
    return user


def restore_managed_user(db: Session, user_id: int, current_user: User, current_identity: UserIdentity) -> User:
    """恢复逻辑删除账号：恢复后账号重新出现在列表中，并可继续登录。"""
    user = get_managed_user(db, user_id, current_user, current_identity, include_deleted=True)
    user.deleted = False
    user.status = True
    for identity in user.identities:
        identity.deleted = False
        identity.status = True
    db.commit()
    db.refresh(user)
    return user
