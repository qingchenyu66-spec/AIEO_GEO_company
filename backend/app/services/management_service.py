import hashlib
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.security import hash_password
from app.models.approval import OperationApproval
from app.models.permission import Position, Role, UserIdentityMenu
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.schemas.permission import UserCreateRequest, UserIdentityCreateItem, UserUpdateRequest
from app.services.permission_service import (
    default_menu_ids_for_position,
    default_menu_ids_for_role,
    replace_identity_menus,
    replace_identity_menus_from_position,
)
from app.services.tenant_scope import is_platform_admin_identity, is_sales_identity

# 2026-07-30 - 创建/改名重名提示（方案 B）- 在册分服务中/停服拦截；软删可再建
TENANT_NAME_WAS_PURGED_HINT = "该名称曾被彻底删除，将新建企业"


def can_manage_all_users(db: Session, identity: UserIdentity) -> bool:
    """平台非销售身份可管理全部用户；销售仅看自己创建的账号。"""
    if identity.identity_type != "PLATFORM":
        return False
    return not is_sales_identity(db, identity)


def _platform_identity_requests_admin(db: Session, item: UserIdentityCreateItem) -> bool:
    """目标身份是否在申请平台管理员职位或角色。"""
    if item.identity_type != "PLATFORM":
        return False
    if str(item.role_code or "").upper() == "PLATFORM_ADMIN":
        return True
    if item.position_id is None:
        return False
    position = db.scalar(
        select(Position).where(
            Position.id == item.position_id,
            Position.deleted.is_(False),
        )
    )
    return bool(position is not None and position.position_code == "PLATFORM_ADMIN")


def assert_actor_can_assign_identities(
    db: Session,
    actor_identity: UserIdentity,
    identities: list[UserIdentityCreateItem],
) -> None:
    """2026-07-30 - 非管理员不可赋管理员职/角，防运营提权。"""
    if is_platform_admin_identity(db, actor_identity):
        return
    for item in identities:
        if _platform_identity_requests_admin(db, item):
            raise PermissionError("仅平台管理员可分配管理员职位或角色")


def assert_actor_can_manage_target_user(db: Session, actor_identity: UserIdentity, target: User) -> None:
    """非管理员不可改已有管理员账号。"""
    if is_platform_admin_identity(db, actor_identity):
        return
    for identity in target.identities:
        if identity.deleted:
            continue
        if is_platform_admin_identity(db, identity):
            raise PermissionError("仅平台管理员可修改管理员账号")


def list_managed_users(
    db: Session,
    current_user: User,
    current_identity: UserIdentity,
    *,
    keyword: str | None = None,
    tenant_id: int | None = None,
    identity_type: str | None = None,
    position_id: int | None = None,
    status: bool | None = None,
    deleted: bool = False,
) -> list[User]:
    stmt = (
        select(User)
        .options(joinedload(User.identities).joinedload(UserIdentity.tenant))
        .where(User.deleted.is_(deleted))
        .order_by(User.id.desc())
    )
    if not can_manage_all_users(db, current_identity):
        stmt = stmt.where(User.created_by == current_user.id)
    if status is not None:
        stmt = stmt.where(User.status.is_(status))

    # 2026-08-05 - 筛销售却出客户管理员 - 软删身份仍被 any() 命中；正常列表只认未删身份
    def identity_any(*extra):
        conds = list(extra)
        if not deleted:
            conds.insert(0, UserIdentity.deleted.is_(False))
        return User.identities.any(and_(*conds) if len(conds) > 1 else conds[0])

    if keyword and keyword.strip():
        like_value = f"%{keyword.strip()}%"
        # 2026-08-05 - 搜索框写「职位」但未命中职位名 - keyword 一并匹配 position_name
        position_ids_by_name = select(Position.id).where(
            Position.deleted.is_(False),
            Position.position_name.like(like_value),
        )
        stmt = stmt.where(
            or_(
                User.username.like(like_value),
                User.display_name.like(like_value),
                identity_any(UserIdentity.identity_name.like(like_value)),
                identity_any(UserIdentity.position_id.in_(position_ids_by_name)),
            )
        )
    if tenant_id is not None:
        stmt = stmt.where(identity_any(UserIdentity.tenant_id == tenant_id))
    # 2026-08-05 - 用户列表按职位筛 - 端+职位必须落在同一身份，避免双身份串匹
    identity_conds = []
    if identity_type:
        identity_conds.append(UserIdentity.identity_type == identity_type)
    if position_id is not None:
        identity_conds.append(UserIdentity.position_id == position_id)
    if identity_conds:
        stmt = stmt.where(identity_any(*identity_conds))
    return list(db.scalars(stmt).unique())


def get_managed_user(
    db: Session,
    user_id: int,
    current_user: User,
    current_identity: UserIdentity,
    *,
    include_deleted: bool = False,
) -> User:
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
    if not can_manage_all_users(db, current_identity) and user.created_by != current_user.id:
        raise ValueError("无权管理该用户")
    return user


def _tenant_code_from_name(name: str) -> str:
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:10].upper()
    return f"TENANT_{digest}"


def apply_tenant_billing_mode_on_create(
    db: Session,
    tenant: Tenant,
    billing_mode: str | None,
    *,
    opening_credit_amount: Decimal | float | int | str | None = None,
    operator_user_id: int | None = None,
) -> None:
    # 2026-08-27 - 新建企业可选算力自助，须同步注入企业配置菜单
    # 2026-09-09 - 创建可选自助；起步算力选填，有值才充值
    mode = (billing_mode or "hosted").strip().lower()
    if mode not in {"hosted", "credit"}:
        raise ValueError("企业类型无效")
    if mode == "hosted":
        tenant.billing_mode = mode
        return

    from app.services.billing_mode_service import inject_enterprise_menus_for_tenant
    from app.services.credit_service import recharge_credits

    tenant.billing_mode = "credit"
    tenant.platform_whitelist_json = []
    opening = None
    if opening_credit_amount is not None and str(opening_credit_amount).strip() != "":
        opening = Decimal(str(opening_credit_amount))
        if opening < 0:
            raise ValueError("起步算力不能为负数")
    if opening is not None and opening > 0:
        op_id = int(operator_user_id or tenant.owner_user_id or 0)
        recharge_credits(
            db,
            tenant,
            opening,
            operator_user_id=op_id,
            reason="新建企业起步充值",
        )
    inject_enterprise_menus_for_tenant(db, tenant.id)


def create_platform_tenant(
    db: Session,
    *,
    name: str,
    owner_user_id: int,
    service_start_date: date | None = None,
    service_end_date: date | None = None,
    preferred_code: str | None = None,
    billing_mode: str | None = "hosted",
    opening_credit_amount: Decimal | float | int | str | None = None,
) -> Tenant:
    """新建在册企业（不 commit）。销售草稿保存 / 审批回放共用。"""
    # 2026-08-18 - 新增企业弹窗不再入库，保存配置时才建租户
    from app.services.tenant_account_service import sync_tenant_accounts_for_service_state

    cleaned = (name or "").strip()
    if len(cleaned) < 2:
        raise ValueError("企业名称至少 2 个字")
    if service_start_date and service_end_date and service_end_date < service_start_date:
        raise ValueError("服务结束日期不能早于服务开始日期")
    preferred = (preferred_code or _tenant_code_from_name(cleaned)).strip()
    raise_if_live_tenant_name_or_code_conflict(db, name=cleaned, code=preferred)
    code = allocate_tenant_code(db, cleaned, preferred)
    today = date.today()
    expired = bool(service_end_date and service_end_date < today)
    not_started = bool(service_start_date and service_start_date > today)
    tenant = Tenant(
        name=cleaned,
        code=code,
        owner_user_id=owner_user_id,
        service_start_date=service_start_date,
        service_end_date=service_end_date,
        status=not expired and not not_started,
        stop_reason="expired" if expired else None,
    )
    if expired:
        tenant.stopped_at = datetime.now()
    db.add(tenant)
    db.flush()
    apply_tenant_billing_mode_on_create(
        db,
        tenant,
        billing_mode,
        opening_credit_amount=opening_credit_amount,
        operator_user_id=owner_user_id,
    )
    if not tenant.status:
        sync_tenant_accounts_for_service_state(db, tenant)
    return tenant


def allocate_tenant_code(db: Session, name: str, preferred: str | None = None) -> str:
    """分配未被占用的企业编码（含软删行，避免 uk 撞车）。"""
    base = (preferred or _tenant_code_from_name(name)).strip() or _tenant_code_from_name(name)
    code = base
    suffix = 0
    while db.scalar(select(Tenant.id).where(Tenant.code == code)) is not None:
        suffix += 1
        code = f"{base}_{suffix}"
        # ponytail: 极端撞库上限；正常不会打满
        if suffix > 1000:
            raise ValueError("企业编码分配失败，请稍后重试")
    return code


def tenant_name_was_purged(db: Session, name: str) -> bool:
    return (
        db.scalar(select(Tenant.id).where(Tenant.name == name, Tenant.deleted.is_(True)).limit(1)) is not None
    )


def live_tenant_name_conflict_detail(tenant: Tenant, name: str) -> str:
    """在册企业重名提示：服务中/未开始 vs 已停服。"""
    today = date.today()
    pending = bool(
        tenant.service_start_date
        and tenant.service_start_date > today
        and tenant.stop_reason != "canceled"
    )
    if tenant.status or pending:
        return f"企业「{name}」已存在且服务中，请勿重复创建"
    return f"企业「{name}」已存在但已停服，请恢复服务或更换名称"


def find_live_tenant_name_or_code_conflict(
    db: Session,
    *,
    name: str,
    code: str,
    exclude_id: int | None = None,
) -> Tenant | None:
    stmt = select(Tenant).where(
        or_(Tenant.name == name, Tenant.code == code),
        Tenant.deleted.is_(False),
    )
    if exclude_id is not None:
        stmt = stmt.where(Tenant.id != exclude_id)
    return db.scalar(stmt)


def raise_if_live_tenant_name_or_code_conflict(
    db: Session,
    *,
    name: str,
    code: str,
    exclude_id: int | None = None,
) -> None:
    exists = find_live_tenant_name_or_code_conflict(db, name=name, code=code, exclude_id=exclude_id)
    if exists is None:
        return
    if exists.name == name:
        raise ValueError(live_tenant_name_conflict_detail(exists, name))
    raise ValueError(f"企业编码「{code}」已存在")


def _approval_new_tenant_name(record: OperationApproval) -> str:
    raw = record.payload_json if isinstance(record.payload_json, dict) else {}
    body = raw.get("body") if isinstance(raw.get("body"), dict) else raw
    if not isinstance(body, dict):
        return ""
    if record.operation_key == "brand.asset.upsert":
        return str(body.get("company_full_name") or body.get("brand_name") or "").strip()
    if record.operation_key == "management.tenant.create":
        return str(body.get("name") or "").strip()
    return ""


def raise_if_new_tenant_name_unavailable(
    db: Session,
    name: str,
    *,
    allow_own_pending_user_id: int | None = None,
) -> None:
    """新建企业名称：拦在册重名，并拦他人（或全部）待审批同名单。"""
    # 2026-08-18 - 同名仍能点下一步进草稿 - 销售列表看不到别人的企业，须在入库前全局校验
    cleaned = (name or "").strip()
    if len(cleaned) < 2:
        raise ValueError("企业名称至少 2 个字")
    exists = db.scalar(
        select(Tenant).where(Tenant.name == cleaned, Tenant.deleted.is_(False)).limit(1)
    )
    if exists is not None:
        raise ValueError(live_tenant_name_conflict_detail(exists, cleaned))
    pending_rows = list(
        db.scalars(
            select(OperationApproval).where(
                OperationApproval.deleted.is_(False),
                OperationApproval.status == "pending",
                OperationApproval.tenant_id.is_(None),
                OperationApproval.operation_key.in_(
                    ("brand.asset.upsert", "management.tenant.create")
                ),
            )
        )
    )
    for record in pending_rows:
        if (
            allow_own_pending_user_id is not None
            and record.requester_user_id == allow_own_pending_user_id
        ):
            continue
        if _approval_new_tenant_name(record) == cleaned:
            raise ValueError(f"企业「{cleaned}」已有待审批的新增申请，请勿重复提交")


def _reject_garbled_text(value: str | None, field_name: str) -> None:
    if value and value.strip() and set(value.strip()) == {"?"}:
        raise ValueError(f"{field_name}疑似编码异常，请重新输入中文后保存")


def _resolve_tenant(db: Session, item: UserIdentityCreateItem, owner_user_id: int | None = None) -> Tenant | None:
    if item.identity_type != "CUSTOMER":
        return None
    if item.tenant_id is not None:
        # ponytail: 未开服/停服仍可绑账号（开服由 login/dependencies 拦）；与按名称解析一致
        tenant = db.scalar(select(Tenant).where(Tenant.id == item.tenant_id, Tenant.deleted.is_(False)))
        if tenant is None:
            raise ValueError("所属企业不存在或已删除")
        return tenant
    if not item.tenant_name or not item.tenant_name.strip():
        raise ValueError("客户企业端账号必须选择或输入所属企业")
    tenant_name = item.tenant_name.strip()
    _reject_garbled_text(tenant_name, "企业名称")
    tenant = db.scalar(select(Tenant).where(Tenant.name == tenant_name, Tenant.deleted.is_(False)))
    if tenant is None:
        # 2026-07-30 - 软删同名再建 - 换新 code，避免与软删行 uk 冲突
        tenant = Tenant(
            name=tenant_name,
            code=allocate_tenant_code(db, tenant_name),
            owner_user_id=owner_user_id,
        )
        db.add(tenant)
        db.flush()
    return tenant


def _resolve_position(db: Session, item: UserIdentityCreateItem) -> Position | None:
    if item.position_id is None:
        return None
    position = db.scalar(
        select(Position).where(
            Position.id == item.position_id,
            Position.identity_type == item.identity_type,
            Position.status.is_(True),
            Position.deleted.is_(False),
        )
    )
    if position is None:
        raise ValueError("职位不存在或已停用")
    return position


def _resolve_identity_name(item: UserIdentityCreateItem, position: Position | None) -> str:
    name = item.identity_name or (position.position_name if position else None)
    if not name:
        name = "平台运营人员" if item.identity_type == "PLATFORM" else "客户企业成员"
    name = name.strip()
    _reject_garbled_text(name, "身份名称")
    return name


def _menu_ids_for_identity(db: Session, item: UserIdentityCreateItem, position: Position | None) -> list[int]:
    if item.menu_ids:
        return item.menu_ids
    if position:
        return default_menu_ids_for_position(db, position.id)
    return default_menu_ids_for_role(db, item.role_code)


def _validate_role(db: Session, item: UserIdentityCreateItem) -> None:
    role = db.scalar(
        select(Role).where(
            Role.role_code == item.role_code,
            Role.identity_type == item.identity_type,
            Role.status.is_(True),
            Role.deleted.is_(False),
        )
    )
    if role is None:
        raise ValueError("角色不存在或已停用")


def _create_identity_for_user(db: Session, user: User, item: UserIdentityCreateItem, *, is_default: bool, owner_user_id: int | None = None) -> None:
    _validate_role(db, item)
    position = _resolve_position(db, item)
    tenant = _resolve_tenant(db, item, owner_user_id)
    identity = UserIdentity(
        identity_code=f"{item.identity_type}_{user.id}_{item.role_code}",
        user_id=user.id,
        tenant_id=tenant.id if tenant else None,
        position_id=position.id if position else None,
        identity_type=item.identity_type,
        identity_name=_resolve_identity_name(item, position),
        role_code=item.role_code,
        is_default=is_default,
    )
    db.add(identity)
    db.flush()
    if position:
        replace_identity_menus_from_position(db, identity.id, position.id)
    else:
        replace_identity_menus(db, identity.id, _menu_ids_for_identity(db, item, position), writable=item.identity_type == "PLATFORM")


def _identity_code_for_user(user: User, item: UserIdentityCreateItem) -> str:
    """Build the stable identity code used by the existing schema."""
    return f"{item.identity_type}_{user.id}_{item.role_code}"


def _find_reusable_identity(db: Session, user: User, item: UserIdentityCreateItem) -> UserIdentity | None:
    """Find an existing identity even if it was previously disabled.

    A user is allowed to own both PLATFORM and CUSTOMER identities, but only one
    row per identity type should be active for the edit form. When an operator
    unchecks CUSTOMER and later checks it again, we must revive the old row
    instead of inserting another row with the same identity_code.
    """
    active_identity = db.scalar(
        select(UserIdentity)
        .where(
            UserIdentity.user_id == user.id,
            UserIdentity.identity_type == item.identity_type,
            UserIdentity.deleted.is_(False),
        )
        .order_by(UserIdentity.id.asc())
    )
    if active_identity is not None:
        return active_identity

    target_code = _identity_code_for_user(user, item)
    coded_identity = db.scalar(select(UserIdentity).where(UserIdentity.identity_code == target_code))
    if coded_identity is not None and coded_identity.user_id == user.id:
        return coded_identity

    return db.scalar(
        select(UserIdentity)
        .where(
            UserIdentity.user_id == user.id,
            UserIdentity.identity_type == item.identity_type,
        )
        .order_by(UserIdentity.id.asc())
    )


def _upsert_identity_for_user(db: Session, user: User, item: UserIdentityCreateItem, *, is_default: bool, owner_user_id: int | None = None) -> None:
    _validate_role(db, item)
    position = _resolve_position(db, item)
    tenant = _resolve_tenant(db, item, owner_user_id)
    identity = _find_reusable_identity(db, user, item)
    if identity is None:
        identity = UserIdentity(
            identity_code=_identity_code_for_user(user, item),
            user_id=user.id,
            identity_type=item.identity_type,
        )
        db.add(identity)
    elif identity.identity_code != _identity_code_for_user(user, item):
        code_exists = db.scalar(select(UserIdentity.id).where(UserIdentity.identity_code == _identity_code_for_user(user, item), UserIdentity.id != identity.id))
        if code_exists is None:
            identity.identity_code = _identity_code_for_user(user, item)
    identity.tenant_id = tenant.id if tenant else None
    identity.position_id = position.id if position else None
    identity.identity_name = _resolve_identity_name(item, position)
    identity.role_code = item.role_code
    identity.is_default = is_default
    identity.status = True
    identity.deleted = False
    db.flush()
    if position:
        replace_identity_menus_from_position(db, identity.id, position.id)
    else:
        replace_identity_menus(db, identity.id, _menu_ids_for_identity(db, item, position), writable=item.identity_type == "PLATFORM")


def create_managed_user(
    db: Session,
    payload: UserCreateRequest,
    creator: User,
    creator_identity: UserIdentity,
    *,
    commit: bool = True,
) -> User:
    # 2026-08-20 - username 库级唯一含软删行；只查未删会漏拦，落成裸 IntegrityError
    username = str(payload.username or "").strip()
    exists = db.scalar(select(User).where(User.username == username))
    if exists is not None:
        if exists.deleted:
            raise ValueError(f"账号「{username}」已删除，请在「已删除账号」中恢复，或更换登录名")
        raise ValueError("账号已存在")
    _reject_garbled_text(payload.display_name, "用户姓名")
    assert_actor_can_assign_identities(db, creator_identity, list(payload.identities))

    user = User(
        username=username,
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
        _create_identity_for_user(db, user, item, is_default=index == 0, owner_user_id=creator.id)

    if commit:
        db.commit()
        db.refresh(user)
    return user


def update_managed_user(
    db: Session,
    user_id: int,
    payload: UserUpdateRequest,
    current_user: User,
    current_identity: UserIdentity,
    *,
    commit: bool = True,
) -> User:
    user = get_managed_user(db, user_id, current_user, current_identity)
    _reject_garbled_text(payload.display_name, "用户姓名")
    assert_actor_can_manage_target_user(db, current_identity, user)
    assert_actor_can_assign_identities(db, current_identity, list(payload.identities))
    identity_types = [item.identity_type for item in payload.identities]
    if len(identity_types) != len(set(identity_types)):
        raise ValueError("同一用户不能重复添加相同登录身份")

    user.display_name = payload.display_name
    remove_types = {item.strip().upper() for item in payload.remove_identity_types if item and item.strip()}
    invalid_remove = remove_types - {"PLATFORM", "CUSTOMER"}
    if invalid_remove:
        raise ValueError(f"无效的 remove_identity_types: {', '.join(sorted(invalid_remove))}")
    if remove_types & set(identity_types):
        raise ValueError("不能同时 upsert 并删除同一登录身份")
    for identity in user.identities:
        if identity.deleted:
            continue
        if identity.identity_type in remove_types:
            identity.deleted = True
            identity.status = False
            db.query(UserIdentityMenu).filter(UserIdentityMenu.identity_id == identity.id).delete(synchronize_session=False)
    for index, item in enumerate(payload.identities):
        _upsert_identity_for_user(db, user, item, is_default=index == 0, owner_user_id=current_user.id)
    if commit:
        db.commit()
        db.refresh(user)
    return user


def reset_managed_user_password(db: Session, user_id: int, password: str, current_user: User, current_identity: UserIdentity) -> None:
    user = get_managed_user(db, user_id, current_user, current_identity)
    user.password_hash = hash_password(password)
    user.must_change_password = False
    db.commit()


def set_managed_user_status(db: Session, user_id: int, enabled: bool, current_user: User, current_identity: UserIdentity) -> User:
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
    user = get_managed_user(db, user_id, current_user, current_identity, include_deleted=True)
    user.deleted = False
    user.status = True
    for identity in user.identities:
        identity.deleted = False
        identity.status = True
    db.commit()
    db.refresh(user)
    return user


def _is_sales_position(position: Position | None) -> bool:
    if position is None or position.deleted:
        return False
    return position.position_code == "PLATFORM_SALES"


def user_has_platform_sales_identity(db: Session, user_id: int) -> bool:
    rows = db.execute(
        select(Position)
        .join(UserIdentity, UserIdentity.position_id == Position.id)
        .where(
            UserIdentity.user_id == user_id,
            UserIdentity.identity_type == "PLATFORM",
            UserIdentity.deleted.is_(False),
            UserIdentity.status.is_(True),
            Position.deleted.is_(False),
        )
    ).scalars()
    return any(_is_sales_position(position) for position in rows)


def list_platform_sales_users(db: Session) -> list[dict]:
    rows = db.execute(
        select(User.id, User.username, User.display_name, User.status)
        .join(UserIdentity, UserIdentity.user_id == User.id)
        .join(Position, Position.id == UserIdentity.position_id)
        .where(
            User.deleted.is_(False),
            User.status.is_(True),
            UserIdentity.deleted.is_(False),
            UserIdentity.status.is_(True),
            UserIdentity.identity_type == "PLATFORM",
            Position.deleted.is_(False),
            Position.position_code == "PLATFORM_SALES",
        )
        .distinct()
        .order_by(User.display_name.asc(), User.id.asc())
    ).all()
    return [
        {
            "id": row.id,
            "username": row.username,
            "display_name": row.display_name,
            "status": row.status,
        }
        for row in rows
    ]


def transfer_tenant_owner(db: Session, tenant_id: int, owner_user_id: int) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted.is_(False)))
    if tenant is None:
        raise ValueError("企业不存在")
    target = db.scalar(select(User).where(User.id == owner_user_id, User.deleted.is_(False), User.status.is_(True)))
    if target is None:
        raise ValueError("目标销售账号不存在或已停用")
    if not user_has_platform_sales_identity(db, owner_user_id):
        raise ValueError("目标账号不是有效的平台销售身份")
    if tenant.owner_user_id == owner_user_id:
        return tenant
    tenant.owner_user_id = owner_user_id
    db.flush()
    return tenant
