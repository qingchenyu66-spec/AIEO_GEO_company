#!/usr/bin/env python3
"""Align REDIS_URL with REDIS_PASSWORD in backend/.env (idempotent)."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

ENV_PATH = Path("/opt/geo/AIEO_GEO/backend/.env")


def main() -> None:
    text = ENV_PATH.read_text(encoding="utf-8")
    password_match = re.search(r"^REDIS_PASSWORD=(.+)$", text, re.MULTILINE)
    if not password_match:
        print("REDIS_PASSWORD missing, skip")
        return
    password = password_match.group(1).strip().strip('"').strip("'")
    if not password:
        print("REDIS_PASSWORD empty, skip")
        return
    encoded = quote(password, safe="")
    new_url = f"redis://:{encoded}@127.0.0.1:6379/0"
    if re.search(r"^REDIS_URL=.*@127\.0\.0\.1:6379/0\s*$", text, re.MULTILINE):
        print("REDIS_URL already has auth")
        return
    if re.search(r"^REDIS_URL=", text, re.MULTILINE):
        text = re.sub(r"^REDIS_URL=.*$", f"REDIS_URL={new_url}", text, count=1, flags=re.MULTILINE)
    else:
        text = text.rstrip() + f"\nREDIS_URL={new_url}\n"
    ENV_PATH.write_text(text, encoding="utf-8")
    print("REDIS_URL updated with password")


if __name__ == "__main__":
    main()
