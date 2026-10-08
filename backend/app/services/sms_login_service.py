"""登录账号手机号与 4 位验证码.

验证码按用途分开: login / bind / change_old / change_new.
创建或管理员填写的手机号立即可用于登录, 不设待确认状态.
观察号不能绑定手机.
"""

from __future__ import annotations

import hmac
import logging
import re
import secrets
import time

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.masking import mask_phone
from app.core.redis_client import get_redis_client, prefixed_key, redis_enabled
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.services.auth_service import LoginRejected, active_identities, login_block_reason
from app.services.observer_account import is_observer_username

logger = logging.getLogger(__name__)

SMS_CODE_LENGTH = 4
SMS_CODE_TTL_SECONDS = 300
SMS_COOLDOWN_SECONDS = 60
SMS_HOURLY_SECONDS = 3600
SMS_MAX_ATTEMPTS = 5
SMS_HOURLY_LIMIT_MESSAGE = "该手机号一小时内发送次数已达上限, 请稍后再试"
SMS_PURPOSES = ("login", "bind", "change_old", "change_new", "password", "reset")
RESET_UNBOUND = "该账号尚未绑定手机号, 请联系管理员重置密码"
_PHONE_RE = re.compile(r"^1\d{10}$")
_CODE_RE = re.compile(r"^\d{4}$")
_MEMORY: dict[str, dict] = {}


def normalize_phone(raw: str | None, *, allow_empty: bool = False) -> str | None:
    text = re.sub(r"\s+", "", str(raw or ""))
    if not text:
        if allow_empty:
            return None
        raise ValueError("请填写手机号")
    if not _PHONE_RE.fullmatch(text):
        raise ValueError("请填写 11 位手机号")
    return text


def apply_login_phone(db: Session, user: User, raw: str | None, *, keep_login_switch: bool = False) -> None:
    """写入登录手机号. 空值解绑并关闭验证码登录. 新号码默认打开开关."""
    phone = normalize_phone(raw, allow_empty=True)
    if is_observer_username(user.username):
        if phone:
            raise ValueError("观察号不能绑定手机号")
        user.phone = None
        user.phone_login_enabled = False
        return
    if phone is None:
        user.phone = None
        user.phone_login_enabled = False
        return
    db.flush()
    taken = db.scalar(select(User.id).where(User.phone == phone, User.id != user.id))
    if taken is not None:
        raise ValueError("该手机号已绑定其他账号")
    same = user.phone == phone
    user.phone = phone
    if keep_login_switch or same:
        return
    user.phone_login_enabled = True


def set_phone_login_enabled(user: User, enabled: bool) -> None:
    """只切换能否用手机号登录, 不改号码."""
    if is_observer_username(user.username):
        raise ValueError("观察号不能使用手机号登录")
    if enabled and not user.phone:
        raise ValueError("请先设置安全手机号")
    user.phone_login_enabled = bool(enabled)


def _code_key(phone: str, purpose: str) -> str:
    return prefixed_key(f"sms:{purpose}:{phone}")


def _cool_key(phone: str, purpose: str) -> str:
    return prefixed_key(f"sms:cool:{purpose}:{phone}")


def _hour_key(phone: str) -> str:
    return prefixed_key(f"sms:hour:{phone}")


def _mem_get(key: str) -> dict | None:
    row = _MEMORY.get(key)
    if row is None:
        return None
    if float(row.get("exp") or 0) <= time.time():
        _MEMORY.pop(key, None)
        return None
    return row


def _mem_set(key: str, payload: dict, ttl: int) -> None:
    _MEMORY[key] = {**payload, "exp": time.time() + ttl}


def _redis():
    if not redis_enabled():
        return None
    client = get_redis_client()
    if client is None:
        raise ValueError("验证码服务暂不可用")
    return client


def _hourly_limit() -> int:
    return max(1, int(settings.sms_hourly_send_limit))


def _hourly_reserve(phone: str) -> None:
    """先占一格小时额度. 发送失败要放回."""
    limit = _hourly_limit()
    key = _hour_key(phone)
    client = _redis()
    if client is None:
        row = _mem_get(key)
        count = (int(row.get("count") or 0) if row else 0) + 1
        if count > limit:
            raise ValueError(SMS_HOURLY_LIMIT_MESSAGE)
        if row is None:
            _mem_set(key, {"count": count}, SMS_HOURLY_SECONDS)
        else:
            row["count"] = count
        return
    count = int(client.incr(key))
    if count == 1:
        client.expire(key, SMS_HOURLY_SECONDS)
    if count > limit:
        client.decr(key)
        raise ValueError(SMS_HOURLY_LIMIT_MESSAGE)


def _hourly_release(phone: str) -> None:
    key = _hour_key(phone)
    client = _redis()
    if client is None:
        row = _MEMORY.get(key)
        if not row:
            return
        row["count"] = max(0, int(row.get("count") or 0) - 1)
        return
    try:
        client.decr(key)
    except Exception:
        logger.warning("sms hourly release failed phone=%s", mask_phone(phone))


def _acquire_cooldown(phone: str, purpose: str) -> None:
    key = _cool_key(phone, purpose)
    client = _redis()
    if client is None:
        if _mem_get(key) is not None:
            raise ValueError("验证码已发送, 请稍后再试")
        _mem_set(key, {"ok": 1}, SMS_COOLDOWN_SECONDS)
        return
    if not client.set(key, "1", ex=SMS_COOLDOWN_SECONDS, nx=True):
        raise ValueError("验证码已发送, 请稍后再试")


def _release_cooldown(phone: str, purpose: str) -> None:
    key = _cool_key(phone, purpose)
    client = _redis()
    if client is None:
        _MEMORY.pop(key, None)
        return
    client.delete(key)


def _drop_code(phone: str, purpose: str) -> None:
    key = _code_key(phone, purpose)
    client = _redis()
    if client is None:
        _MEMORY.pop(key, None)
        return
    client.delete(key)


def abort_unsent(phone: str, purpose: str) -> None:
    """发送失败: 去掉验证码, 放开 60 秒, 退回小时额度."""
    _drop_code(phone, purpose)
    _release_cooldown(phone, purpose)
    _hourly_release(phone)


def issue_code(phone: str, purpose: str) -> str:
    if purpose not in SMS_PURPOSES:
        raise ValueError("验证码用途无效")
    _hourly_reserve(phone)
    try:
        _acquire_cooldown(phone, purpose)
    except ValueError:
        _hourly_release(phone)
        raise
    code = f"{secrets.randbelow(10 ** SMS_CODE_LENGTH):0{SMS_CODE_LENGTH}d}"
    key = _code_key(phone, purpose)
    client = _redis()
    try:
        if client is None:
            _mem_set(key, {"code": code, "attempts": 0}, SMS_CODE_TTL_SECONDS)
        else:
            client.set(key, f"{code}:0", ex=SMS_CODE_TTL_SECONDS)
    except Exception:
        _release_cooldown(phone, purpose)
        _hourly_release(phone)
        raise
    return code


def dispatch_code(phone: str, purpose: str) -> str | None:
    """占额度并发送. 只有发出去才保留小时次数和 60 秒冷却."""
    code = issue_code(phone, purpose)
    try:
        return deliver_code(phone, code)
    except Exception:
        abort_unsent(phone, purpose)
        raise


def _account_for_phone(db: Session, phone: str) -> User | None:
    return db.scalar(
        select(User)
        .options(joinedload(User.identities).joinedload(UserIdentity.tenant))
        .where(User.phone == phone, User.deleted.is_(False))
    )


def check_code(phone: str, purpose: str, raw_code: str, *, consume: bool) -> None:
    code = str(raw_code or "").strip()
    if not _CODE_RE.fullmatch(code):
        raise ValueError("请输入 4 位验证码")
    key = _code_key(phone, purpose)
    client = _redis()
    if client is None:
        row = _mem_get(key)
        if row is None:
            raise ValueError("手机号或验证码错误")
        stored = str(row.get("code") or "")
        attempts = int(row.get("attempts") or 0)
        if attempts >= SMS_MAX_ATTEMPTS:
            _MEMORY.pop(key, None)
            raise ValueError("验证码已失效, 请重新获取")
        if not hmac.compare_digest(stored, code):
            row["attempts"] = attempts + 1
            if row["attempts"] >= SMS_MAX_ATTEMPTS:
                _MEMORY.pop(key, None)
                raise ValueError("验证码已失效, 请重新获取")
            raise ValueError("手机号或验证码错误")
        if consume:
            _MEMORY.pop(key, None)
        return

    raw = client.get(key)
    if not raw:
        raise ValueError("手机号或验证码错误")
    stored, _, attempt_text = str(raw).partition(":")
    attempts = int(attempt_text or "0")
    ttl = int(client.ttl(key) or SMS_CODE_TTL_SECONDS)
    if ttl < 1:
        ttl = SMS_CODE_TTL_SECONDS
    if attempts >= SMS_MAX_ATTEMPTS:
        client.delete(key)
        raise ValueError("验证码已失效, 请重新获取")
    if not hmac.compare_digest(stored, code):
        attempts += 1
        if attempts >= SMS_MAX_ATTEMPTS:
            client.delete(key)
            raise ValueError("验证码已失效, 请重新获取")
        client.set(key, f"{stored}:{attempts}", ex=ttl)
        raise ValueError("手机号或验证码错误")
    if consume:
        client.delete(key)


def deliver_code(phone: str, code: str) -> str | None:
    """发出验证码. 短信未启用且 debug 时把码回给调用方, 便于本地试用."""
    template = str(settings.aliyun_sms_template_code_login or "SMS_338355304").strip()
    if not settings.aliyun_sms_enabled:
        if settings.debug:
            logger.info("sms code kept for local debug phone=%s", mask_phone(phone))
            return code
        raise ValueError("短信未启用")
    from app.services.aliyun_sms_service import send_sms

    send_sms(phone=phone, template_code=template, template_param={"code": code})
    return None


def _user_for_phone(db: Session, phone: str) -> User | None:
    user = _account_for_phone(db, phone)
    if user is None or not user.status or is_observer_username(user.username):
        return None
    if not bool(getattr(user, "phone_login_enabled", True)):
        return None
    if not active_identities(user):
        return None
    return user


def request_login_code(db: Session, raw_phone: str) -> str | None:
    phone = normalize_phone(raw_phone)
    assert phone is not None
    user = _account_for_phone(db, phone)
    if user is None or is_observer_username(user.username):
        raise ValueError("该手机号尚未绑定, 请用账号密码登录, 或联系管理员绑定")
    if not user.status or not active_identities(user):
        raise ValueError(login_block_reason(user))
    if not bool(getattr(user, "phone_login_enabled", True)):
        raise ValueError("该手机号未开启验证码登录")
    return dispatch_code(phone, "login")


def _require_bindable(user: User) -> None:
    if is_observer_username(user.username):
        raise ValueError("观察号不能绑定手机号")


def request_account_code(db: Session, user: User, purpose: str, raw_phone: str | None) -> str | None:
    _require_bindable(user)
    if purpose == "bind":
        if user.phone:
            raise ValueError("已绑定手机号, 请使用更换")
        phone = normalize_phone(raw_phone)
        assert phone is not None
        taken = db.scalar(select(User.id).where(User.phone == phone, User.id != user.id))
        if taken is not None:
            raise ValueError("该手机号已绑定其他账号")
    elif purpose == "change_old":
        if not user.phone:
            raise ValueError("尚未绑定手机号")
        phone = user.phone
    elif purpose == "password":
        if not user.phone:
            raise ValueError("尚未绑定手机号, 请先到账号与安全绑定")
        phone = user.phone
    elif purpose == "change_new":
        if not user.phone:
            raise ValueError("尚未绑定手机号")
        phone = normalize_phone(raw_phone)
        assert phone is not None
        if phone == user.phone:
            raise ValueError("新手机号不能与当前手机号相同")
        taken = db.scalar(select(User.id).where(User.phone == phone, User.id != user.id))
        if taken is not None:
            raise ValueError("该手机号已绑定其他账号")
    else:
        raise ValueError("验证码用途无效")
    return dispatch_code(phone, purpose)


def change_password_with_code(db: Session, user: User, *, code: str, new_password: str) -> None:
    """已绑定手机的验证码通过后更新登录密码."""
    from app.core.security import hash_password, verify_password

    _require_bindable(user)
    if not user.phone:
        raise ValueError("尚未绑定手机号, 请先到账号与安全绑定")
    password = str(new_password or "").strip()
    if len(password) < 6:
        raise ValueError("新密码至少 6 个字符")
    if verify_password(password, user.password_hash):
        raise ValueError("新密码不能与当前密码相同")
    check_code(user.phone, "password", code, consume=True)
    user.password_hash = hash_password(password)
    user.must_change_password = False
    from app.services.auth_service import mark_password_changed

    mark_password_changed(user)
    db.flush()


def _user_for_reset(db: Session, username: str) -> User:
    """未登录找回: 账号不存在, 观察号, 没绑手机, 都用同一句, 不暴露账号是否存在."""
    from app.services.auth_service import get_user_for_login, login_block_reason

    name = str(username or "").strip()
    user = get_user_for_login(db, name) if name else None
    if user is None or is_observer_username(user.username) or not user.phone:
        raise ValueError(RESET_UNBOUND)
    if not user.status or not active_identities(user):
        raise ValueError(login_block_reason(user))
    return user


def preview_reset(db: Session, username: str) -> str:
    """只确认能否找回, 不发短信."""
    user = _user_for_reset(db, username)
    return mask_phone(str(user.phone))


def request_reset_code(db: Session, username: str) -> tuple[str, str | None]:
    """向该账号已绑定手机发找回码. 验证码登录开关关掉也不影响找回."""
    user = _user_for_reset(db, username)
    phone = str(user.phone)
    return mask_phone(phone), dispatch_code(phone, "reset")


def reset_password_with_username(db: Session, username: str, *, code: str, new_password: str) -> None:
    from app.core.security import hash_password, verify_password

    user = _user_for_reset(db, username)
    password = str(new_password or "").strip()
    if len(password) < 6:
        raise ValueError("新密码至少 6 个字符")
    if verify_password(password, user.password_hash):
        raise ValueError("新密码不能与当前密码相同")
    check_code(str(user.phone), "reset", code, consume=True)
    user.password_hash = hash_password(password)
    user.must_change_password = False
    from app.services.auth_service import mark_password_changed

    mark_password_changed(user)
    db.flush()


def authenticate_sms(db: Session, raw_phone: str, raw_code: str):
    phone = normalize_phone(raw_phone)
    assert phone is not None
    check_code(phone, "login", raw_code, consume=True)
    user = _user_for_phone(db, phone)
    if user is None:
        blocked = db.scalar(select(User).where(User.phone == phone, User.deleted.is_(False)))
        if blocked is not None and not blocked.status:
            raise LoginRejected(login_block_reason(blocked))
        raise ValueError("手机号或验证码错误")
    identities = active_identities(user)
    if not identities:
        raise LoginRejected(login_block_reason(user))
    return user, identities


def bind_phone(db: Session, user: User, raw_phone: str, raw_code: str) -> None:
    _require_bindable(user)
    if user.phone:
        raise ValueError("已绑定手机号, 请使用更换")
    phone = normalize_phone(raw_phone)
    assert phone is not None
    check_code(phone, "bind", raw_code, consume=True)
    apply_login_phone(db, user, phone)


def change_phone(db: Session, user: User, *, old_code: str, new_phone: str, new_code: str) -> None:
    _require_bindable(user)
    if not user.phone:
        raise ValueError("尚未绑定手机号")
    target = normalize_phone(new_phone)
    assert target is not None
    check_code(user.phone, "change_old", old_code, consume=False)
    check_code(target, "change_new", new_code, consume=False)
    check_code(user.phone, "change_old", old_code, consume=True)
    check_code(target, "change_new", new_code, consume=True)
    apply_login_phone(db, user, target, keep_login_switch=True)
