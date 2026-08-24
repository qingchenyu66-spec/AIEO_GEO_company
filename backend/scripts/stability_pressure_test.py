#!/usr/bin/env python
"""稳定性压测脚本（桌面方案⑦）：并发打健康检查 / 工作台 / 矩阵，观察快通道是否仍可用。

用法（需本地 API 已起、有登录 cookie 或 Bearer）：

  cd backend
  $env:PYTHONPATH="."
  .\.venv\Scripts\python.exe scripts/stability_pressure_test.py --base http://127.0.0.1:8001 --token <JWT>

不传 --token 时只压公开 /health。
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _request(method: str, url: str, *, token: str | None, timeout: float) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, method=method, headers=headers)
    started = time.perf_counter()
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            ms = int((time.perf_counter() - started) * 1000)
            return {
                "ok": 200 <= resp.status < 300,
                "status": resp.status,
                "ms": ms,
                "bytes": len(body),
            }
    except HTTPError as exc:
        ms = int((time.perf_counter() - started) * 1000)
        return {"ok": False, "status": int(exc.code), "ms": ms, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        ms = int((time.perf_counter() - started) * 1000)
        return {"ok": False, "status": 0, "ms": ms, "error": str(exc)}


def _summary(label: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    ms_list = [int(r["ms"]) for r in rows if "ms" in r]
    oks = sum(1 for r in rows if r.get("ok"))
    return {
        "label": label,
        "n": len(rows),
        "ok": oks,
        "fail": len(rows) - oks,
        "p50_ms": int(statistics.median(ms_list)) if ms_list else None,
        "p95_ms": int(sorted(ms_list)[max(0, int(len(ms_list) * 0.95) - 1)]) if ms_list else None,
        "max_ms": max(ms_list) if ms_list else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="GEO 稳定性轻量压测")
    parser.add_argument("--base", default="http://127.0.0.1:8001")
    parser.add_argument("--token", default="")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--tenant-id", type=int, default=0, help="平台预览企业；客户 token 可不传")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    token = str(args.token or "").strip() or None

    jobs: list[tuple[str, str]] = []
    for _ in range(args.rounds):
        jobs.append(("health", f"{base}/api/v1/health"))
        if token:
            qs = f"?tenant_id={args.tenant_id}" if args.tenant_id else ""
            jobs.append(("workspace", f"{base}/api/v1/monitor/workspace-brief{qs}"))
            jobs.append(("matrix", f"{base}/api/v1/monitor/ranking-matrix{qs}&async_miss=false" if qs else f"{base}/api/v1/monitor/ranking-matrix?async_miss=false"))

    # 交错：每个 round 先打一批矩阵/工作台，同时夹杂 health，验证快通道
    interleaved: list[tuple[str, str]] = []
    by_label: dict[str, list[tuple[str, str]]] = {}
    for label, url in jobs:
        by_label.setdefault(label, []).append((label, url))
    max_len = max(len(v) for v in by_label.values())
    for i in range(max_len):
        for label in ("matrix", "workspace", "health"):
            bucket = by_label.get(label) or []
            if i < len(bucket):
                interleaved.append(bucket[i])

    results: dict[str, list[dict[str, Any]]] = {"health": [], "workspace": [], "matrix": []}
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futs = {
            pool.submit(_request, "GET", url, token=token if label != "health" else None, timeout=args.timeout): label
            for label, url in interleaved
        }
        for fut in as_completed(futs):
            label = futs[fut]
            results.setdefault(label, []).append(fut.result())

    report = {
        "base": base,
        "concurrency": args.concurrency,
        "rounds": args.rounds,
        "summaries": [_summary(k, v) for k, v in results.items() if v],
        "pass": True,
    }
    health = next((s for s in report["summaries"] if s["label"] == "health"), None)
    # 判定：健康检查失败率 < 5%，且 P95 < 2s
    if health:
        fail_rate = (health["fail"] / health["n"]) if health["n"] else 1
        if fail_rate > 0.05 or (health.get("p95_ms") or 0) > 2000:
            report["pass"] = False
            report["reason"] = "快通道 /health 在压力下不达标（失败率>5% 或 P95>2s）"
    else:
        report["pass"] = False
        report["reason"] = "无 health 样本"

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
