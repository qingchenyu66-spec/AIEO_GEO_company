"""本地联调：销售提交 → 运营驳回 → 销售 resubmit → 运营通过。"""

from __future__ import annotations

import json
import sys
import uuid
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8001/api/v1"
SALES = ("Yangbojing", "Geo@2026")
REVIEWER = ("demo", "Geo@2026")
MARK = "联调驳回复活"
CSRF_COOKIE = "geo_csrf_token"


class Session:
    """Cookie + 可选 Bearer；适配 auth_cookie_enabled 本地联调。"""

    def __init__(self) -> None:
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.token = ""

    def _csrf_header(self) -> dict[str, str]:
        for cookie in self.jar:
            if cookie.name == CSRF_COOKIE and cookie.value:
                return {"X-CSRF-Token": cookie.value}
        return {}

    def req(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
    ) -> tuple[int, dict]:
        url = f"{BASE}{path}"
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        headers.update(self._csrf_header())
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"detail": raw}
            return exc.code, payload

    def login_as(self, username: str, password: str, *, position_code: str | None = None) -> None:
        code, payload = self.req("POST", "/auth/login", body={"username": username, "password": password})
        if code != 200 or payload.get("code") != 0:
            raise RuntimeError(f"登录失败 {username}: {code} {payload}")
        data = payload["data"]
        if not data.get("requires_identity_selection"):
            session = data.get("session") or {}
            token = session.get("access_token")
            if token:
                self.token = str(token)
            return
        identities = data.get("identities") or []
        if position_code:
            picked = next((i for i in identities if i.get("position_code") == position_code), None)
            if picked is None:
                raise RuntimeError(f"无身份 {position_code}: {identities}")
            identity_id = int(picked["id"])
        else:
            identity_id = int(identities[0]["id"])
        code, payload = self.req(
            "POST",
            "/auth/select-identity",
            body={"ticket": data["ticket"], "identity_id": identity_id},
        )
        if code != 200 or payload.get("code") != 0:
            raise RuntimeError(f"选身份失败: {code} {payload}")
        token = payload.get("data", {}).get("access_token")
        if token:
            self.token = str(token)


def main() -> None:
    print("=== 1. 销售登录并提交售前诊断审批 ===")
    sales = Session()
    sales.login_as(*SALES, position_code="PLATFORM_SALES")
    brand = f"{MARK}-{uuid.uuid4().hex[:8]}"
    create_body = {
        "brand_name": brand,
        "prompts": ["LED广告公司推荐", "公交广告公司哪家好", "广告公司排名", "本地广告服务", "品牌介绍"],
        "competitors": ["竞品A"],
        "platforms": ["doubao"],
        "region_codes": [],
        "contact_note": "初次提交",
        "schedule_days": 3,
        "start_immediately": False,
    }
    code, payload = sales.req("POST", "/lead-diagnosis", body=create_body)
    if code != 200 or payload.get("code") != 0:
        raise RuntimeError(f"销售创建失败: {code} {payload}")
    data = payload.get("data") or {}
    if not data.get("pending_approval"):
        raise RuntimeError(f"销售未进审批队列: {data}")
    approval_id = int(data["id"])
    print(f"  待审单 #{approval_id}")

    print("=== 2. 运营驳回 ===")
    reviewer = Session()
    reviewer.login_as(*REVIEWER)
    code, payload = reviewer.req(
        "POST",
        f"/approvals/{approval_id}/reject",
        body={"comment": "请补充竞品与平台"},
    )
    if code != 200 or payload.get("code") != 0:
        raise RuntimeError(f"驳回失败: {code} {payload}")
    rejected = payload.get("data") or {}
    if rejected.get("status") != "rejected":
        raise RuntimeError(f"状态未变 rejected: {rejected}")
    print(f"  已驳回：{rejected.get('review_comment')}")

    print("=== 3. 销售 resubmit ===")
    create_body["competitors"] = ["竞品A", "竞品B"]
    create_body["platforms"] = ["doubao", "kimi"]
    create_body["contact_note"] = "已补竞品和平台"
    code, payload = sales.req(
        "POST",
        f"/approvals/{approval_id}/resubmit",
        body={"body": create_body},
    )
    if code != 200 or payload.get("code") != 0:
        raise RuntimeError(f"resubmit 失败: {code} {payload}")
    pending = payload.get("data") or {}
    if pending.get("status") != "pending" or not pending.get("resubmitted"):
        raise RuntimeError(f"resubmit 异常: {pending}")
    body = pending.get("lead_adopted_body") or (pending.get("payload") or {}).get("body") or {}
    if body.get("competitors") != ["竞品A", "竞品B"]:
        raise RuntimeError(f"payload 未更新: {body.get('competitors')}")
    print(f"  已复活 pending，resubmit_count={pending.get('resubmit_count')}")

    print("=== 4. 运营通过并执行 ===")
    code, payload = reviewer.req(
        "POST",
        f"/approvals/{approval_id}/approve",
        body={"comment": "联调通过"},
    )
    if code != 200 or payload.get("code") != 0:
        raise RuntimeError(f"通过失败: {code} {payload}")
    approved = payload.get("data") or {}
    if approved.get("status") != "approved":
        raise RuntimeError(f"通过后非 approved: {approved}")
    executed = approved.get("executed_result") or {}
    lead_id = executed.get("id") or (executed.get("result") or {}).get("id")
    print(f"  已通过并执行，lead_id={lead_id}")

    print("=== 5. 复核终态 ===")
    code, payload = reviewer.req("GET", f"/approvals/{approval_id}")
    final = payload.get("data") or {}
    if final.get("status") != "approved":
        raise RuntimeError(f"终态异常: {final}")
    print(f"  approved，驳回历史 {len(final.get('rejection_history') or [])} 条")

    print("\n✅ 本地联调通过：销售提交 → 驳回 → resubmit → 通过")


if __name__ == "__main__":
    main()
