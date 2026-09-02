#!/usr/bin/env python3
"""售前诊断任务配置修改 - 本地/生产烟测。"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from http.cookiejar import CookieJar

sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_BASE = "http://127.0.0.1:8001/api/v1"
MARK = "配置修改烟测"
CSRF_COOKIE = "geo_csrf_token"


def _future_slots(count: int = 3) -> list[str]:
    base = datetime.now().replace(second=0, microsecond=0) + timedelta(days=2)
    return [(base + timedelta(hours=5 * i)).strftime("%Y-%m-%dT%H:%M") for i in range(count)]


class SessionClient:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.token = ""

    def _csrf_header(self) -> dict[str, str]:
        for cookie in self.jar:
            if cookie.name == CSRF_COOKIE and cookie.value:
                return {"X-CSRF-Token": cookie.value}
        return {}

    def _req(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        headers.update(self._csrf_header())
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            headers=headers,
            method=method,
        )
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

    def login(self, username: str, password: str, *, position_code: str | None = None) -> None:
        code, payload = self._req("POST", "/auth/login", body={"username": username, "password": password})
        if code != 200 or payload.get("code") != 0:
            raise RuntimeError(f"登录失败 {username}: {code} {payload}")
        data = payload["data"]
        if not data.get("requires_identity_selection"):
            token = (data.get("session") or {}).get("access_token")
            if token:
                self.token = str(token)
            return
        identities = data.get("identities") or []
        if position_code:
            picked = next(i for i in identities if i.get("position_code") == position_code)
            identity_id = int(picked["id"])
        else:
            identity_id = int(identities[0]["id"])
        code, payload = self._req(
            "POST",
            "/auth/select-identity",
            body={"ticket": data["ticket"], "identity_id": identity_id},
        )
        if code != 200 or payload.get("code") != 0:
            raise RuntimeError(f"选身份失败 {username}: {code} {payload}")
        token = payload["data"].get("access_token")
        if token:
            self.token = str(token)

    def post(self, path: str, json: dict | None = None) -> dict:
        code, payload = self._req("POST", path, body=json)
        if code >= 400 or payload.get("code") not in (0, None):
            raise RuntimeError(f"POST {path} -> {code} {payload}")
        return payload["data"]

    def get(self, path: str) -> dict:
        code, payload = self._req("GET", path)
        if code >= 400 or payload.get("code") not in (0, None):
            raise RuntimeError(f"GET {path} -> {code} {payload}")
        return payload["data"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--lead-id", type=int, default=0, help="已有 lead 时跳过建单，直接改配置")
    args = parser.parse_args()

    sales = SessionClient(args.base)
    demo = SessionClient(args.base)
    sales.login("Yangbojing", "Geo@2026", position_code="PLATFORM_SALES")
    demo.login("demo", "Geo@2026")

    if args.lead_id > 0:
        lead_id = args.lead_id
        before = demo.get(f"/lead-diagnosis/{lead_id}")
        print(f"reuse lead #{lead_id} brand={before.get('brand_name')}")
    else:
        brand = f"{MARK}-{uuid.uuid4().hex[:8]}"
        pending = sales.post("/lead-diagnosis", json={
            "brand_name": brand,
            "prompts": ["LED广告公司推荐", "公交广告公司哪家好", "广告公司排名", "本地广告服务", "品牌介绍"],
            "competitors": ["烟测竞品"],
            "platforms": ["doubao"],
            "region_codes": [],
            "schedule_days": 3,
            "start_immediately": False,
        })
        approval_id = int(pending["id"])
        executed = demo.post(f"/approvals/{approval_id}/approve", json={"comment": "烟测通过"})
        lead_id = int((executed.get("executed_result") or {}).get("id") or (executed.get("result") or {}).get("id"))
        before = demo.get(f"/lead-diagnosis/{lead_id}")
        print(f"created lead #{lead_id} brand={brand}")

    slots = _future_slots(3)
    revised = demo.post(f"/lead-diagnosis/{lead_id}/revise-config", json={
        "competitors": ["烟测竞品A", "烟测竞品B"],
        "platforms": ["doubao", "kimi"],
        "schedule_datetimes": slots,
        "contact_note": "烟测改配置",
    })
    assert revised.get("platforms") == before.get("platforms"), revised
    assert revised.get("schedule_datetimes") == slots, revised
    assert int(revised.get("schedule_total_count") or 0) == len(slots), revised
    print("OK revise-config")
    print(f"  platforms locked: {revised.get('platforms')}")
    print(f"  schedule_total_count={revised.get('schedule_total_count')} slots={len(slots)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise
