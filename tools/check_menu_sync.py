#!/usr/bin/env python3
"""Прогон синхронизации меню на живом HTTP.

Тесты подменяют загрузку, чтобы проверить решения. Здесь проверяется другое:
что POS действительно ходит по сети за каталогом, разбирает его и показывает
новинку официанту. Каталог для этого раздаётся локально — с настоящего сайта
он берётся тем же кодом и по тому же адресу.

    python3 tools/check_menu_sync.py [каталог Menu-qr]
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "/workspace/envyyy-uk/menu-qr")
PORT = 8765
API = "http://127.0.0.1:8000"

fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ok  " if ok else " FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def api(path: str, method: str = "GET", cookies: str = "", body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(API + path, method=method, data=data)
    request.add_header("Content-Type", "application/json")
    if cookies:
        request.add_header("Cookie", cookies)
    with urllib.request.urlopen(request, timeout=20) as answer:
        raw = answer.read().decode()
        set_cookie = answer.headers.get_all("Set-Cookie") or []
        jar = "; ".join(c.split(";")[0] for c in set_cookie)
        return (json.loads(raw) if raw else None), jar


def main() -> None:
    catalogue = SRC / "data" / "menu.json"
    if not catalogue.exists():
        sys.exit(f"нет каталога: {catalogue}")

    # Копия каталога, которую можно править, не трогая исходный репозиторий.
    root = Path(tempfile.mkdtemp(prefix="menu-site-"))
    (root / "data").mkdir()
    shutil.copy(catalogue, root / "data" / "menu.json")
    shutil.copy(SRC / "data" / "ui.json", root / "data" / "ui.json")

    site = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(1.5)
        _, jar = api("/api/auth/pin", "POST", body={"pin": "123456"})

        state, _ = api("/api/admin/menu/sync", cookies=jar)
        if str(PORT) not in (state.get("url") or ""):
            # Прогон не может перенастроить чужой сервер, но и делать вид,
            # что проверил, не должен.
            print("сервер смотрит не на этот каталог:", state.get("url"))
            print("\nПодняться так:\n"
                  f'  MENU_SOURCE_URL="http://127.0.0.1:{PORT}/data/menu.json" \\\n'
                  f'  MENU_LABELS_URL="http://127.0.0.1:{PORT}/data/ui.json" \\\n'
                  "  uvicorn app.main:app --app-dir backend")
            sys.exit(1)
        check("сервер знает адрес каталога", bool(state["url"]), str(state))

        result, _ = api("/api/admin/menu/sync", "POST", cookies=jar)
        check("каталог скачан и разобран", result["status"] == "ok", json.dumps(result, ensure_ascii=False)[:200])

        menu, _ = api("/api/menu", cookies=jar)
        check("меню на месте", len(menu["items"]) == 63, str(len(menu["items"])))
        check("кальян с зависимой группой уцелел",
              any(g.get("depends") for i in menu["items"] if i["key"] == "hookah"
                  for g in i["options"]))

        # Админ добавляет позицию на сайте — ровно то, ради чего всё это.
        data = json.loads((root / "data" / "menu.json").read_text(encoding="utf-8"))
        data["items"].append({
            "key": "test-negroni-bianco",
            "name": "Negroni Bianco",
            "category": "cocktails",
            "station": "bar",
            "price_pence": 1700,
            "desc": {"ru": "Джин, белый вермут, горький ликёр"},
            "alt": ["негрони бьянко"],
        })
        (root / "data" / "menu.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )

        result, _ = api("/api/admin/menu/sync", "POST", cookies=jar)
        check("новая позиция приехала",
              "Negroni Bianco" in (result.get("report") or {}).get("added", []),
              json.dumps(result, ensure_ascii=False)[:200])

        menu, _ = api("/api/menu", cookies=jar)
        added = next((i for i in menu["items"] if i["key"] == "test-negroni-bianco"), None)
        check("официант видит её в меню", added is not None)
        check("с ценой, посчитанной сервером", added and added["price_pence"] == 1700)
        check("и находит по-русски", added and "негрони бьянко" in added["search_terms"])

        # Позицию убрали — она пропадает из продажи, но не из базы.
        data["items"] = [i for i in data["items"] if i["key"] != "test-negroni-bianco"]
        (root / "data" / "menu.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        result, _ = api("/api/admin/menu/sync", "POST", cookies=jar)
        check("убранная позиция ушла из продажи",
              "Negroni Bianco" in (result.get("report") or {}).get("removed", []),
              json.dumps(result, ensure_ascii=False)[:200])
        menu, _ = api("/api/menu", cookies=jar)
        check("её больше не предлагают официанту",
              all(i["key"] != "test-negroni-bianco" for i in menu["items"]))
        check("но меню целиком на месте", len(menu["items"]) == 63, str(len(menu["items"])))
    finally:
        site.terminate()
        shutil.rmtree(root, ignore_errors=True)

    print()
    if fails:
        print("не прошло:", ", ".join(fails))
        sys.exit(1)
    print("меню приезжает с сайта")


if __name__ == "__main__":
    main()
