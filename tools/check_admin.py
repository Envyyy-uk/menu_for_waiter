#!/usr/bin/env python3
"""Прогон админки в настоящем браузере.

Главный вопрос спринта: можно ли завести заведение с нуля, не заходя в
консоль. Здесь он и проверяется — сотрудник заводится через окно, получает
PIN, и этим PIN сразу входит.

    python3 tools/check_admin.py [http://127.0.0.1:8000]
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = next(
    (str(p) for p in sorted(Path("/opt/pw-browsers").glob("chromium*/chrome-linux/chrome"))),
    None,
)
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
DESK = {"width": 1280, "height": 900}
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
    fresh_pin = f"{random.randrange(1000, 9999)}"
    name = f"Тест{random.randrange(100, 999)}"
    table = str(random.randrange(200, 999))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        ctx = browser.new_context(viewport=DESK)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(BASE + "/admin/", wait_until="networkidle")
        # У админки свой PIN и он длиннее: отсюда правят цены, роли и склад.
        check("вход в админку просит шесть цифр",
              page.locator("#pin-dots i").count() == 6,
              str(page.locator("#pin-dots i").count()))
        check("с экрана админки есть ссылка в зал",
              page.locator(".gate .elsewhere").count() == 1)
        pin(page, "123456")
        check("владелец видит все разделы",
              page.locator(".tab").count() == 10, str(page.locator(".tab").count()))
        # Подписи набраны капителью средствами оформления — сравниваем без
        # учёта регистра, иначе проверка ломается от смены шрифта.
        check("смена открывается первой",
              "выручка" in page.locator(".panel").inner_text().lower())

        # Сотрудник заводится из окна, а не из консоли.
        page.get_by_role("button", name="Персонал").click()
        page.wait_for_timeout(700)
        page.get_by_placeholder("Имя").fill(name)
        page.get_by_placeholder("PIN,").fill(fresh_pin)
        page.get_by_role("button", name="Завести сотрудника").click()
        page.wait_for_timeout(900)
        check("PIN показан один раз и крупно",
              fresh_pin in page.locator(".pin-shown").inner_text(),
              page.locator(".pin-shown").inner_text()[:80])
        page.get_by_role("button", name="Записал").click()
        page.wait_for_timeout(400)
        check("сотрудник появился в списке", name in page.locator("table.grid").inner_text())

        # Этим PIN он сразу входит — в своё приложение.
        staff_ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
        staff = staff_ctx.new_page()
        staff.goto(BASE, wait_until="networkidle")
        pin(staff, fresh_pin)
        check("новый сотрудник вошёл своим PIN",
              staff.locator(":is(.plan, .tables)").count() > 0, staff.url)
        check("вошёл под своим именем", name in staff.locator("#who").inner_text())
        staff_ctx.close()

        # Стол заводится оттуда же — на плане зала, а не в таблице координат.
        page.get_by_role("button", name="Столы").click()
        page.wait_for_timeout(800)
        check("зал показан планом", page.locator(".plan .spot").count() > 0)

        page.get_by_role("button", name="Добавить стол").click()
        page.wait_for_timeout(500)
        page.locator(".sheet .field").first.fill(table)
        page.get_by_role("button", name="Поставить в зал").click()
        page.wait_for_timeout(1000)
        check("стол встал в зал",
              page.locator(f".plan .spot:has(.n:text-is('{table}'))").count() == 1)

        # Зал ставят целиком: несколько столов одной формой.
        many = str(random.randrange(300, 899))
        page.get_by_role("button", name="Добавить стол").click()
        page.wait_for_timeout(500)
        page.locator(".sheet .field").nth(0).fill(many)
        page.locator(".sheet .field").nth(2).fill("4")
        page.get_by_role("button", name="Поставить в зал").click()
        page.wait_for_timeout(1400)
        added = [str(int(many) + n) for n in range(4)]
        check("четыре стола встали одной формой",
              all(page.locator(f".plan .spot:has(.n:text-is('{n}'))").count() == 1
                  for n in added),
              page.locator(".plan-bar").inner_text().replace("\n", " "))

        # И убираются оттуда же — по ним не было чеков.
        for n in added:
            page.locator(f".plan .spot:has(.n:text-is('{n}'))").click()
            page.wait_for_timeout(400)
            page.get_by_role("button", name="Убрать стол").click()
            page.wait_for_timeout(900)
        check("и убираются обратно",
              all(page.locator(f".plan .spot:has(.n:text-is('{n}'))").count() == 0
                  for n in added))

        # И убирается: по нему ещё не было чеков.
        page.locator(f".plan .spot:has(.n:text-is('{table}'))").click()
        page.wait_for_timeout(500)
        page.get_by_role("button", name="Убрать стол").click()
        page.wait_for_timeout(1000)
        check("и убирается, пока по нему не было чеков",
              page.locator(f".plan .spot:has(.n:text-is('{table}'))").count() == 0)

        # Цена меняется и попадает в журнал.
        page.get_by_role("button", name="Меню").click()
        page.wait_for_timeout(900)
        page.locator("tr", has_text="Mojito").locator("button", has_text="Цена").first.click()
        page.wait_for_timeout(500)
        page.locator(".sheet .field").fill("18.50")
        page.get_by_role("button", name="Сохранить").click()
        page.wait_for_timeout(900)
        check("новая цена в списке",
              "£18.50" in page.locator("tr", has_text="Mojito").first.inner_text(),
              page.locator("tr", has_text="Mojito").first.inner_text())

        page.get_by_role("button", name="Журнал").click()
        page.wait_for_timeout(900)
        journal = page.locator("table.grid").inner_text()
        check("правка цены записана с именем",
              "Правка меню" in journal and "Владелец" in journal,
              journal[:200])
        check("новый сотрудник записан", "Новый сотрудник" in journal)

        check("ошибок в консоли нет", not errors, "; ".join(errors[:3]))
        browser.close()

    print()
    if fails:
        print("не прошло:", ", ".join(fails))
        sys.exit(1)
    print("админка работает")


if __name__ == "__main__":
    main()
