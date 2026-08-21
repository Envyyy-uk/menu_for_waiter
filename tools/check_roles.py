#!/usr/bin/env python3
"""Прогон ролей в настоящем браузере.

Проверяется то, что видно человеку: бармен пробивает и тут же видит свои
марки; официант марок не видит вовсе и свой PIN не меняет.

    python3 tools/check_roles.py [http://127.0.0.1:8000]
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = next(
    (str(p) for p in sorted(Path("/opt/pw-browsers").glob("chromium*/chrome-linux/chrome"))),
    None,
)
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PHONE = {"width": 390, "height": 844}
FREE_TABLE = ":is(.spot, .tile):not(.busy)"

fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ok  " if ok else " FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def pin(page, code: str) -> None:
    for digit in code:
        page.get_by_role("button", name=digit, exact=True).click()
    page.wait_for_function("() => !Auth.busy", timeout=10000)
    page.wait_for_timeout(800)


def leave(page) -> None:
    """«Выйти» закрывает смену и спрашивает PIN. Для прогона уходим, не
    закрывая: проверяем роли, а не табель."""
    page.get_by_role("button", name="Выйти").click()
    page.wait_for_timeout(700)
    away = page.get_by_role("button", name="Выйти, не закрывая смену")
    if away.count():
        away.click()
    page.wait_for_timeout(900)


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        # --- официант: марок нет ------------------------------------------
        page.goto(BASE, wait_until="networkidle")
        pin(page, "1111")
        check("официант попадает в зал", page.locator(".plan, .tables").count() > 0)
        check("у официанта нет кнопки марок",
              page.get_by_role("button", name="Марки").count() == 0)

        # Свой PIN официант не меняет: PIN в зале — не пароль от почты, а
        # ключ от кассы. Забыл — новый выдаст менеджер, и это видно в журнале.
        check("у официанта нет кнопки смены PIN",
              page.get_by_role("button", name="Сменить PIN").count() == 0)

        # --- бармен: зал и марки в одном приложении ------------------------
        leave(page)
        pin(page, "2222")
        check("бармен попадает в зал, а не на планшет",
              page.locator(".plan, .tables").count() > 0, page.url)
        check("у бармена есть переключатель марок",
              page.get_by_role("button", name="Столы").count() == 1
              and page.locator(".dock .btn").count() == 2)

        # Бармен пробивает сам за стойкой.
        page.locator(FREE_TABLE).first.click()
        page.wait_for_timeout(400)
        page.get_by_role("button", name="Открыть стол").click()
        page.wait_for_timeout(900)
        check("бармен может набрать заказ", page.locator(".dish").count() > 0)
        page.locator(".search input").fill("мохито")
        page.wait_for_timeout(400)
        page.locator(".dish").first.click()
        page.wait_for_timeout(500)
        page.get_by_role("button", name="К чеку").click()
        page.wait_for_timeout(400)
        page.get_by_role("button", name="Отправить").click()
        page.wait_for_timeout(1200)

        page.get_by_role("button", name="←").click()
        page.wait_for_timeout(600)
        marks = page.locator(".dock .btn").nth(1)
        check("счётчик марок вырос", "·" in marks.inner_text(), marks.inner_text())
        marks.click()
        page.wait_for_timeout(700)
        check("бармен видит свою марку", page.locator(".mark").count() >= 1)
        check("и может её принять",
              page.locator(".mark").first.get_by_role("button", name="Принял").count() == 1)
        page.locator(".mark").first.get_by_role("button", name="Готово").click()
        page.wait_for_timeout(900)
        check("после «Готово» марка ждёт официанта",
              "ждёт официанта" in page.locator(".mark").first.inner_text().lower(),
              page.locator(".mark").first.inner_text()[:80])

        check("ошибок в консоли нет", not errors, "; ".join(errors[:3]))
        browser.close()

    print()
    if fails:
        print("не прошло:", ", ".join(fails))
        sys.exit(1)
    print("роли работают")


if __name__ == "__main__":
    main()
