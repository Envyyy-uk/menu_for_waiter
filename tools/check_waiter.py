#!/usr/bin/env python3
"""Прогон приложения официанта в настоящем браузере.

Тесты API говорят, что сервер считает правильно. Здесь другой вопрос: может
ли официант с телефона в руке пройти путь от пустого стола до закрытого чека,
ни разу не застряв.

    python3 tools/check_waiter.py [http://127.0.0.1:8000]
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

fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ok  " if ok else " FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def pin(page, code: str) -> None:
    for digit in code:
        page.get_by_role("button", name=digit, exact=True).click()
    page.wait_for_function("() => !Auth.busy", timeout=10000)
    page.wait_for_timeout(700)


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(BASE, wait_until="networkidle")
        pin(page, "1111")
        check("официант попадает на столы", page.locator(".tables").count() > 0, page.url)

        free = page.locator(".tile:not(.busy)").first
        label = free.locator(".num").inner_text()
        free.click()
        page.wait_for_timeout(400)
        check("спрашивают число гостей", page.locator(".sheet").is_visible())
        page.get_by_role("button", name="+").click()
        page.get_by_role("button", name="Открыть стол").click()
        page.wait_for_timeout(900)
        check("после открытия сразу меню", page.locator(".dish").count() > 0)

        # Позиция без вариантов — одно нажатие, без лишнего экрана.
        page.get_by_text("Margherita Pizza", exact=True).click()
        page.wait_for_timeout(600)
        check("простая позиция добавляется одним нажатием",
              not page.locator(".sheet").is_visible())

        # Позиция с вариантами — шторка, и без выбора добавить нельзя.
        page.locator(".search input").fill("водка")
        page.wait_for_timeout(400)
        check("поиск по-русски находит английское название",
              page.locator(".dish").count() > 0,
              str(page.locator(".dish").count()))
        page.locator(".dish").first.click()
        page.wait_for_timeout(400)
        disabled = page.get_by_role("button", name="Выберите вариант")
        check("без обязательного варианта добавить нельзя", disabled.count() > 0)
        # Выбор берётся по группам, а не по подписи: «50 мл» есть и внутри
        # «150 мл», и тест не должен угадывать.
        groups = page.locator(".sheet .group")
        groups.nth(0).locator(".opt").first.click()   # объём — 50 мл
        groups.nth(1).locator(".opt").first.click()   # вид — Absolut
        page.wait_for_timeout(300)
        add = page.locator(".sheet .btn.primary")
        check("цена варианта показана до отправки", "£13.00" in add.inner_text(), add.inner_text())
        add.click()
        page.wait_for_timeout(700)

        page.get_by_role("button", name="К чеку").click()
        page.wait_for_timeout(600)
        check("в чеке две позиции", page.locator(".line").count() == 2,
              str(page.locator(".line").count()))
        check("итог посчитан", "£26.00" in page.locator(".totals").inner_text(),
              page.locator(".totals").inner_text())
        check("черновик помечен", page.locator(".line.draft").count() == 2)

        page.get_by_role("button", name="Отправить").click()
        page.wait_for_timeout(900)
        check("после отправки черновиков нет", page.locator(".line.draft").count() == 0)
        check("появилась кнопка оплаты", page.get_by_role("button", name="Оплата").count() > 0)

        page.get_by_role("button", name="Оплата").click()
        page.wait_for_timeout(400)
        page.get_by_role("button", name="Наличные · £26.00").click()
        page.wait_for_timeout(400)
        page.locator(".sheet .field").fill("30")
        page.wait_for_timeout(300)
        check("сдача посчитана", "£4.00" in page.locator(".sheet").inner_text(),
              page.locator(".sheet").inner_text()[:200])
        page.get_by_role("button", name="Принял £26.00").click()
        page.wait_for_timeout(1200)

        check("вернулись к столам", page.locator(".tables").count() > 0)
        tile = page.locator(f".tile:has(.num:text-is('{label}'))")
        check("стол снова свободен", "busy" not in (tile.get_attribute("class") or ""),
              tile.get_attribute("class") or "")

        check("ошибок в консоли нет", not errors, "; ".join(errors[:3]))
        browser.close()

    print()
    if fails:
        print("не прошло:", ", ".join(fails))
        sys.exit(1)
    print("зал работает")


if __name__ == "__main__":
    main()
