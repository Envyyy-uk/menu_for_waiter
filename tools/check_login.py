#!/usr/bin/env python3
"""Проверка входа в настоящем браузере.

Тесты API говорят, что сервер отвечает правильно. Этот скрипт отвечает на
другой вопрос: доходит ли это до человека — попадает ли официант на свой
экран, а бар на свой, и видно ли ошибку, когда PIN неверный.

    python3 tools/check_login.py [http://127.0.0.1:8000]
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

# Браузер уже стоит в образе; путь ищем, а не зашиваем.
CHROME = next(
    (
        str(p)
        for p in sorted(Path("/opt/pw-browsers").glob("chromium*/chrome-linux/chrome"))
    ),
    None,
)

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PHONE = {"width": 390, "height": 844}

fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ok  " if ok else " FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def type_pin(page, pin: str) -> None:
    """Набрать PIN и дождаться ответа.

    Ждать фиксированные полсекунды нельзя: пока сервер проверяет PIN, экран
    намеренно не принимает нажатия — иначе одно касание уходило бы дважды.
    Тест, который этого не ждёт, набирает следующий PIN в пустоту.
    """
    for digit in pin:
        page.get_by_role("button", name=digit, exact=True).click()
    page.wait_for_function(
        "() => !Auth.busy && (!document.getElementById('pin-msg')"
        " || document.getElementById('pin-msg').textContent !== ''"
        " || !document.getElementById('gate'))",
        timeout=10000,
    )


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
        page = ctx.new_page()

        page.goto(BASE, wait_until="networkidle")
        check("экран PIN закрывает всё до входа", page.locator("#gate").is_visible())
        check("цифры PIN не показываются", page.locator("#pin-dots i").count() == 4)

        type_pin(page, "0000")
        check(
            "неверный PIN показывает ошибку",
            "PIN" in (page.locator("#pin-msg").inner_text() or ""),
            page.locator("#pin-msg").inner_text(),
        )

        # У админки свой вход и свой PIN — длиннее. Экран зала ждёт четыре
        # цифры, поэтому владелец идёт по ссылке рядом, а не набирает шесть в
        # четыре точки.
        page.locator(".gate .elsewhere").click()
        page.wait_for_load_state("networkidle")
        check("в админке шесть точек вместо четырёх",
              page.locator("#pin-dots i").count() == 6,
              str(page.locator("#pin-dots i").count()))

        type_pin(page, "123456")
        page.wait_for_timeout(700)
        check("владелец попал в админку", "/admin" in page.url, page.url)
        check("имя видно в шапке", "Владелец" in page.locator("#who").inner_text())

        page.get_by_role("button", name="Выйти").click()
        page.wait_for_timeout(800)
        check("после выхода снова спрашивают PIN", page.locator("#gate").is_visible())

        browser.close()

    print()
    if fails:
        print("не прошло:", ", ".join(fails))
        sys.exit(1)
    print("вход работает")


if __name__ == "__main__":
    main()
