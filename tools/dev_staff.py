#!/usr/bin/env python3
"""Заводит смену для прогонов в браузере: официант, бармен, кухня, менеджер.

Проверки из `tools/check_*.py` входят готовыми PIN-ами, а сидер создаёт
только владельца — заведению не нужен персонал с известными PIN-ами.
Поэтому персонал для прогона заводится отдельно и явно.

    python3 tools/dev_staff.py [http://127.0.0.1:8000]
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OWNER = "123456"

CAST = [
    ("Аня", "waiter", "1111"),
    ("Игорь", "bar", "2222"),
    ("Пётр", "kitchen", "3333"),
    ("Марина", "manager", "444444"),
]


def call(path: str, body: dict | None = None, cookie: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method="POST" if data else "GET")
    req.add_header("content-type", "application/json")
    if cookie:
        req.add_header("cookie", cookie)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read() or b"null"), r.headers.get_all("set-cookie") or []


def main() -> None:
    _, cookies = call("/api/auth/pin", {"pin": OWNER})
    jar = "; ".join(c.split(";")[0] for c in cookies)

    for name, role, pin in CAST:
        try:
            call("/api/admin/users", {"name": name, "role": role, "pin": pin}, jar)
            print(f"  завёл {name} ({role}), PIN {pin}")
        except Exception as exc:            # PIN занят — значит, уже заводили
            print(f"  {name}: {exc}")


if __name__ == "__main__":
    main()
