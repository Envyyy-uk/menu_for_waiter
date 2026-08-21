#!/usr/bin/env python3
"""Прогон склада в настоящем браузере.

Главный вопрос: уходит ли бутылка с полки сама, когда официант отправил
заказ, — и видно ли это владельцу, не заглядывая в базу.

    python3 tools/check_stock.py [http://127.0.0.1:8000]
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
DESK = {"width": 1280, "height": 950}
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


def row_of(page, name: str):
    return page.locator("tr", has_text=name).first


def main() -> None:
    good = f"Absolut-{random.randrange(100, 999)}"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        ctx = browser.new_context(viewport=DESK)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(BASE + "/admin/", wait_until="networkidle")
        pin(page, "123456")
        check("владелец видит склад", page.get_by_role("button", name="Склад").count() == 1)
        page.get_by_role("button", name="Склад").click()
        page.wait_for_timeout(900)

        # Заводим бутылку.
        page.get_by_placeholder("Название (Absolut, лимоны…)").fill(good)
        page.locator(".form select").first.select_option("ml")
        page.get_by_placeholder("Сколько сейчас").fill("1000")
        page.get_by_placeholder("Порог «мало»").fill("200")
        page.get_by_role("button", name="Завести позицию").click()
        page.wait_for_timeout(1200)
        check("позиция склада заведена", row_of(page, good).count() == 1)
        check("остаток показан в мл", "1000" in row_of(page, good).inner_text(),
              row_of(page, good).inner_text())

        # Стартовый остаток — это приход, а не «просто число».
        row_of(page, good).get_by_role("button", name="История").click()
        page.wait_for_timeout(800)
        check("стартовый остаток записан приходом",
              "Приход" in page.locator(".sheet").inner_text(),
              page.locator(".sheet").inner_text()[:120])
        page.locator(".veil, .sheet-bg").first.click()
        page.wait_for_timeout(400)

        # Правило: 50 мл водки на порцию.
        forms = page.locator(".form")
        recipe = forms.last
        recipe.locator("select").nth(0).select_option(label="Absolut")
        page.wait_for_timeout(300)
        recipe.locator("select").nth(1).select_option(label="Объём: 50 мл")
        recipe.locator("select").nth(2).select_option(label=good)
        # Поле ищем по подписи: ряд безымянных окошек уже один раз довёл до
        # того, что форму нельзя было заполнить, не читая исходники.
        recipe.locator(".field-box", has_text="Сколько уходит").locator("input").fill("50")
        page.get_by_role("button", name="Добавить правило").click()
        page.wait_for_timeout(1200)
        check("правило добавлено", page.locator("tr", has_text="50 мл").count() >= 1)

        # Официант продаёт две порции.
        waiter_ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
        waiter = waiter_ctx.new_page()
        waiter.goto(BASE, wait_until="networkidle")
        pin(waiter, "1111")
        waiter.locator(FREE_TABLE).first.click()
        waiter.wait_for_timeout(400)
        waiter.get_by_role("button", name="Открыть стол").click()
        waiter.wait_for_timeout(900)
        waiter.locator(".search input").fill("водка")
        waiter.wait_for_timeout(400)
        waiter.locator(".dish").first.click()
        waiter.wait_for_timeout(400)
        # Вид больше не выбирают: Absolut и Stoli — разные позиции меню, и
        # на полке это разные бутылки.
        groups = waiter.locator(".sheet .group")
        groups.nth(0).locator(".opt").first.click()      # 50 мл
        waiter.locator(".sheet [data-qty], .sheet .stepper button").last.click()  # ещё одна
        waiter.wait_for_timeout(300)
        waiter.locator(".sheet .btn.primary").click()
        waiter.wait_for_timeout(600)
        waiter.get_by_role("button", name="К чеку").click()
        waiter.wait_for_timeout(500)

        page.get_by_role("button", name="Склад").click()
        page.wait_for_timeout(900)
        check("черновик склада не трогает", "1000" in row_of(page, good).inner_text(),
              row_of(page, good).inner_text())

        waiter.get_by_role("button", name="Отправить").click()
        waiter.wait_for_timeout(1400)

        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1200)
        page.get_by_role("button", name="Склад").click()
        page.wait_for_timeout(900)
        check("продажа списала со склада сама",
              "900" in row_of(page, good).inner_text(),
              row_of(page, good).inner_text())

        row_of(page, good).get_by_role("button", name="История").click()
        page.wait_for_timeout(800)
        text = page.locator(".sheet").inner_text()
        check("в истории видно, что это продажа и кто отправил",
              "Продажа" in text and "Аня" in text, text[:160])
        page.locator(".veil, .sheet-bg").first.click()
        page.wait_for_timeout(400)

        # Инвентаризация записывает разницу.
        row_of(page, good).get_by_role("button", name="Движение").click()
        page.wait_for_timeout(500)
        page.locator(".sheet .field").first.fill("850")
        page.get_by_role("button", name="Насчитали на полке").click()
        page.wait_for_timeout(1200)
        check("инвентаризация поправила остаток",
              "850" in row_of(page, good).inner_text(),
              row_of(page, good).inner_text())
        row_of(page, good).get_by_role("button", name="История").click()
        page.wait_for_timeout(800)
        check("и записала разницу, а не новое число",
              "-50" in page.locator(".sheet").inner_text(),
              page.locator(".sheet").inner_text()[:160])
        page.locator(".veil, .sheet-bg").first.click()
        page.wait_for_timeout(400)

        # Менеджеру склад не показывают вовсе.
        page.get_by_role("button", name="Выйти").click()
        page.wait_for_timeout(900)
        pin(page, "444444")
        check("менеджер склада не видит",
              page.get_by_role("button", name="Склад").count() == 0)

        check("ошибок в консоли нет", not errors, "; ".join(errors[:3]))
        browser.close()

    print()
    if fails:
        print("не прошло:", ", ".join(fails))
        sys.exit(1)
    print("склад работает")


if __name__ == "__main__":
    main()
