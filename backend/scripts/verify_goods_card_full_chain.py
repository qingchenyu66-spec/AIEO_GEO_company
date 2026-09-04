"""商品卡一期全链路烟测：开关、菜单、summary API、平台预览。"""
from __future__ import annotations

import json
import sys
from typing import Any

import requests

BASE = "http://127.0.0.1:8001/api/v1"
DEMO = ("demo", "Geo@2026")
AIDIYA_CUSTOMER = ("Xin", "Geo@2026")  # tenant 6 艾迪亚
DISABLED_CUSTOMER = ("jinoutuliao", "Geo@2026")  # tenant 15，默认未开通


class Check:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def ok(self, name: str, detail: str = "") -> None:
        self.passed += 1
        print(f"PASS  {name}" + (f" — {detail}" if detail else ""))

    def fail(self, name: str, detail: str) -> None:
        self.failed += 1
        print(f"FAIL  {name} — {detail}")

    def skip(self, name: str, detail: str) -> None:
        self.skipped += 1
        print(f"SKIP  {name} — {detail}")


def login(username: str, password: str, identity_type: str | None = None) -> tuple[requests.Session, dict[str, Any]]:
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"username": username, "password": password}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"login {username}: {r.status_code} {r.text[:300]}")
    data = r.json().get("data") or {}
    if not data.get("requires_identity_selection"):
        session = data.get("session") or data
        token = session.get("access_token")
        if token:
            s.headers["Authorization"] = f"Bearer {token}"
        return s, session

    ticket = data.get("ticket")
    if not ticket:
        raise RuntimeError(f"no ticket for {username}")
    identities = data.get("identities") or []
    target = identities[0]
    if identity_type:
        for item in identities:
            if item.get("identity_type") == identity_type:
                target = item
                break
    sel = s.post(
        f"{BASE}/auth/select-identity",
        json={"ticket": ticket, "identity_id": target["id"]},
        timeout=30,
    )
    if sel.status_code != 200:
        raise RuntimeError(f"select identity: {sel.status_code} {sel.text[:300]}")
    picked = sel.json().get("data") or {}
    token = picked.get("access_token")
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s, picked


def menu_codes(session: requests.Session) -> list[str]:
    r = session.get(f"{BASE}/auth/me", timeout=30)
    if r.status_code != 200:
        return []
    data = r.json().get("data") or {}
    items = data.get("menus") or []
    return [str(x.get("menu_code") or x.get("code") or "") for x in items]


def main() -> int:
    c = Check()
    print("=== 商品卡全链路烟测 ===\n")

    # 1. 健康检查
    try:
        h = requests.get(f"{BASE}/health", timeout=10)
        if h.status_code == 200:
            c.ok("health")
        else:
            c.fail("health", str(h.status_code))
    except Exception as exc:
        c.fail("health", str(exc))
        print("\n后端未启动，退出")
        return 1

    # 2. 艾迪亚客户：菜单含商品卡 + summary 200
    try:
        s, _ = login(*AIDIYA_CUSTOMER, identity_type="CUSTOMER")
        codes = menu_codes(s)
        if "customer.goods_cards" in codes:
            c.ok("aidiya customer menu", "customer.goods_cards 可见")
        else:
            c.fail("aidiya customer menu", f"缺失，当前 {codes}")

        r = s.get(f"{BASE}/analytics/goods-cards/summary", params={"days": 7}, timeout=60)
        if r.status_code == 200:
            body = r.json().get("data") or {}
            kpi = body.get("kpi") or {}
            c.ok(
                "aidiya customer summary",
                f"sample_total={body.get('sample_total')} out_rate={kpi.get('out_rate')} hits={len(body.get('hits') or [])}",
            )
            required = {"sample_total", "goods_task_total", "kpi", "diagnosis", "hits", "denominator_platforms"}
            missing = required - set(body.keys())
            if missing:
                c.fail("aidiya summary shape", f"缺字段 {missing}")
            else:
                c.ok("aidiya summary shape")
        else:
            c.fail("aidiya customer summary", f"{r.status_code} {r.text[:200]}")
    except Exception as exc:
        c.fail("aidiya customer flow", str(exc))

    # 3. 未开通企业客户：菜单不含商品卡 + API 403
    try:
        s2, _ = login(*DISABLED_CUSTOMER, identity_type="CUSTOMER")
        codes2 = menu_codes(s2)
        if "customer.goods_cards" not in codes2:
            c.ok("disabled tenant menu hidden")
        else:
            c.fail("disabled tenant menu hidden", "不应出现 customer.goods_cards")

        r2 = s2.get(f"{BASE}/analytics/goods-cards/summary", timeout=30)
        if r2.status_code in (403, 400):
            c.ok("disabled tenant summary blocked", str(r2.status_code))
        else:
            c.fail("disabled tenant summary blocked", f"期望 403/400，得 {r2.status_code}")
    except Exception as exc:
        c.fail("disabled tenant flow", str(exc))

    # 4. 平台 demo：预览艾迪亚 tenant_id=6
    try:
        sp, _ = login(*DEMO, identity_type="PLATFORM")
        r3 = sp.get(
            f"{BASE}/analytics/goods-cards/summary",
            params={"tenant_id": 6, "days": 7},
            timeout=60,
        )
        if r3.status_code == 200:
            body3 = r3.json().get("data") or {}
            c.ok("platform preview aidiya", f"sample_total={body3.get('sample_total')}")
        else:
            c.fail("platform preview aidiya", f"{r3.status_code} {r3.text[:200]}")
    except Exception as exc:
        c.fail("platform preview flow", str(exc))

    # 5. 平台读企业管理：goods_card_enabled 字段
    try:
        sp2, _ = login(*DEMO, identity_type="PLATFORM")
        r4 = sp2.get(f"{BASE}/management/tenants/6", timeout=30)
        if r4.status_code == 200:
            t = (r4.json().get("data") or {}).get("tenant") or r4.json().get("data") or {}
            enabled = t.get("goods_card_enabled")
            if enabled is True:
                c.ok("tenant detail goods_card_enabled", "true")
            else:
                c.fail("tenant detail goods_card_enabled", str(enabled))
        else:
            c.fail("tenant detail", f"{r4.status_code}")
    except Exception as exc:
        c.fail("tenant detail flow", str(exc))

    # 6. 前端路由 200
    try:
        fe = requests.get("http://127.0.0.1:5173/", timeout=10)
        if fe.status_code == 200:
            c.ok("frontend dev server")
        else:
            c.fail("frontend dev server", str(fe.status_code))
    except Exception as exc:
        c.fail("frontend dev server", str(exc))

    print(f"\n=== 结果: PASS {c.passed} / FAIL {c.failed} / SKIP {c.skipped} ===")
    return 0 if c.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
