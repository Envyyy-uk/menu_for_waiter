#!/usr/bin/env python3
"""Скидка перед оплатой и список оплат в админке.

Два вопроса, на которые отвечает этот прогон:

1. Может ли менеджер, стоя у стола, снять скидку до того, как назвал сумму, —
   и остаётся ли от этого след.
2. Видно ли потом в админке, за что именно взяли деньги: позиции, скидка с
   причиной, способ оплаты.

    python3 tools/check_payments.py [http://127.0.0.1:8000]
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
DESK = {"width": 1280, "height": 900}
FREE_TABLE = ":is(.spot, .tile):not(.busy)"
HALL = ":is(.plan, .tables)"

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
        errors: list[str] = []

        # ---- зал: менеджер набирает чек и даёт скидку перед оплатой --------
        # Вход у менеджера один — через админку, шестью цифрами. В зал он
        # уходит оттуда: скидку и отмену он даёт у стола, а не из подсобки.
        ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(BASE, wait_until="networkidle")
        check("в зал входят четырьмя цифрами",
              page.locator("#pin-dots i").count() == 4,
              str(page.locator("#pin-dots i").count()))

        page.goto(BASE + "/admin/", wait_until="networkidle")
        pin(page, "444444")     # менеджер: скидка — его решение
        check("менеджер вошёл шестью цифрами", "/admin" in page.url, page.url)
        page.locator("#hall").click()
        page.wait_for_timeout(1200)
        check("из админки есть дорога в зал", page.locator(HALL).count() > 0, page.url)

        page.locator(FREE_TABLE).first.click()
        page.wait_for_timeout(400)
        # Через DOM: шторка прибита к низу окна, и playwright, докручивая до
        # кнопки, промахивается мимо неё в эмуляции телефона. Человеку в этом
        # месте кликать не по чему — проверяем не попадание пальцем, а то, что
        # происходит после нажатия.
        page.evaluate("""() => [...document.querySelectorAll('#sheet button')]
            .find(b => b.textContent.includes('Открыть')).click()""")
        page.wait_for_timeout(900)
        page.get_by_text("Margherita Pizza", exact=True).click()
        page.wait_for_timeout(500)
        page.get_by_role("button", name="К чеку").click()
        page.wait_for_timeout(600)
        page.get_by_role("button", name="Отправить").click()
        page.wait_for_timeout(900)

        page.get_by_role("button", name="Оплата").click()
        page.wait_for_timeout(500)
        check("скидка предлагается до оплаты, а не после",
              page.get_by_role("button", name="Скидка").count() == 1)

        page.get_by_role("button", name="Скидка").click()
        page.wait_for_timeout(400)
        # Процент задаётся ползунком: скидку называют в процентах, и любая
        # от нуля до ста законна, а не четыре заранее выбранные.
        page.locator(".sheet .range").fill("10")
        page.locator(".sheet .range").dispatch_event("input")
        page.wait_for_timeout(300)
        check("процент виден крупно", "10%" in page.locator(".sheet .pc").inner_text(),
              page.locator(".sheet .pc").inner_text())
        sheet = page.locator(".sheet").inner_text()
        check("процент посчитан от позиций", "£1.30" in sheet, sheet[:160])
        page.get_by_placeholder("Причина").fill("ждали долго")
        page.get_by_role("button", name="Применить").click()
        page.wait_for_timeout(900)

        pay = page.locator(".sheet").inner_text()
        check("к оплате уменьшилось", "£11.70" in pay, pay[:200])
        page.get_by_role("button", name="Карта · £11.70").click()
        page.wait_for_timeout(1200)
        check("чек закрылся", page.locator(HALL).count() > 0)

        # ---- админка: за что именно взяли деньги ---------------------------
        admin_ctx = browser.new_context(viewport=DESK)
        admin = admin_ctx.new_page()
        admin.on("pageerror", lambda e: errors.append(str(e)))
        admin.goto(BASE + "/admin/", wait_until="networkidle")
        pin(admin, "123456")

        admin.get_by_role("button", name="Оплаты").click()
        admin.wait_for_timeout(900)
        table = admin.locator("table.grid").inner_text()
        check("закрытый чек виден в оплатах", "Марина" in table, table[:200])
        check("способ оплаты назван", "карта" in table.lower(), table[:200])
        check("скидка видна в строке", "−£1.30" in table, table[:200])

        admin.locator("table.grid tbody tr").first.click()
        admin.wait_for_timeout(600)
        inside = admin.locator(".sheet").inner_text()
        check("видно, что было внутри чека", "Margherita" in inside, inside[:200])
        check("причина скидки записана", "ждали долго" in inside, inside[:200])
        check("итог сходится", "£11.70" in inside, inside[:200])

        # ---- чужой экран официанта не пускает ------------------------------
        waiter_ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
        waiter = waiter_ctx.new_page()
        waiter.goto(BASE + "/admin/", wait_until="networkidle")
        for digit in "1111":
            waiter.get_by_role("button", name=digit, exact=True).click()
        waiter.wait_for_timeout(800)
        # Четыре цифры на экране админки не открывают ничего: там ждут шесть,
        # и неполный набор никуда не уходит — чужих неудачных попыток официант
        # этим не наделает.
        check("официант не войдёт в админку четырьмя цифрами",
              waiter.locator("#gate").count() == 1, waiter.url)

        waiter.locator(".gate .elsewhere").click()
        waiter.wait_for_load_state("networkidle")
        pin(waiter, "1111")
        check("а по ссылке рядом входит в зал теми же цифрами",
              waiter.locator(HALL).count() > 0, waiter.url)

        check("ошибок в консоли нет", not errors, "; ".join(errors[:3]))
        browser.close()

    print()
    if fails:
        print("не прошло:", ", ".join(fails))
        sys.exit(1)
    print("оплаты работают")


if __name__ == "__main__":
    main()
