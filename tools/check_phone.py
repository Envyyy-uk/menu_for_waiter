#!/usr/bin/env python3
"""Прогон на телефоне — экран 390 px и палец вместо мыши.

Всё остальное проверяется на настольном экране, и это скрывало целый класс
поломок: таблица шире экрана растягивает страницу, браузер отъезжает, чтобы
всё влезло, — и кнопки становятся размером со спичечную головку, а шторка
уезжает за край. Со стороны это выглядит как «ничего не работает».

    python3 tools/check_phone.py [http://127.0.0.1:8000]
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
PHONE = {"width": 390, "height": 844}
TABS = ["Смена", "Оплаты", "Табель", "Персонал", "Столы", "Станции", "Меню", "Склад", "Журнал"]

fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ok  " if ok else " FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def pin(page, code: str) -> None:
    for digit in code:
        page.get_by_role("button", name=digit, exact=True).click()
    page.wait_for_function("() => !Auth.busy", timeout=10000)
    page.wait_for_timeout(900)


def main() -> None:
    name = f"Проба{random.randrange(100, 999)}"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(BASE + "/admin/", wait_until="networkidle")
        pin(page, "123456")

        # Главное: страница не расползается вбок ни на одной вкладке.
        wide = []
        for tab in TABS:
            if not page.get_by_role("button", name=tab).count():
                continue
            page.get_by_role("button", name=tab).click()
            page.wait_for_timeout(700)
            size = page.evaluate("() => [document.documentElement.scrollWidth, innerWidth]")
            if size[0] > size[1] + 1:
                wide.append(f"{tab} {size[0]}>{size[1]}")
        check("ни одна вкладка не растягивает страницу", not wide, ", ".join(wide))

        # Широкая таблица при этом всё-таки листается вбок — внутри себя.
        page.get_by_role("button", name="Меню").click()
        page.wait_for_timeout(800)
        check("широкая таблица листается вбок внутри себя",
              page.evaluate("""() => {
                  const box = document.querySelector('.scroller');
                  return !!box && box.scrollWidth > box.clientWidth;
              }"""))

        # Сотрудник заводится и его видно в списке.
        page.get_by_role("button", name="Персонал").click()
        page.wait_for_timeout(800)
        page.get_by_placeholder("Имя").fill(name)
        page.get_by_role("button", name="Завести сотрудника").click()
        page.wait_for_timeout(1200)
        check("PIN показан", page.locator(".pin-shown").count() == 1)
        # Кнопка в шторке должна быть достижима пальцем: раньше её перекрывал фон.
        box = page.locator(".sheet button").last.bounding_box()
        hit = page.evaluate(
            "p => { const n = document.elementFromPoint(p[0], p[1]); return n ? n.tagName + '.' + n.className : null; }",
            [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2],
        )
        check("кнопка в шторке не перекрыта фоном", "BUTTON" in (hit or ""), str(hit))
        page.get_by_role("button", name="Записал").click()
        page.wait_for_timeout(900)
        check("сотрудник в списке", name in page.locator("table.grid").inner_text())

        # И убирается совсем — он ещё ни разу не работал.
        row = page.locator("table.grid tr", has_text=name)
        check("у не работавшего есть «убрать совсем»",
              row.locator("button", has_text="Убрать совсем").count() == 1,
              str(row.locator("button").all_inner_texts()))
        row.locator("button", has_text="Убрать совсем").click()
        page.wait_for_timeout(1200)
        check("и убрался", name not in page.locator("table.grid").inner_text())

        # Стол открывается пальцем: тап — карточка, а не «перетащили на ноль».
        page.get_by_role("button", name="Столы").click()
        page.wait_for_timeout(900)
        spot = page.locator(".plan.editing .spot").first
        at = spot.bounding_box()
        page.touchscreen.tap(at["x"] + at["width"] / 2, at["y"] + at["height"] / 2)
        page.wait_for_timeout(800)
        check("тап по столу открывает карточку", page.locator(".sheet").count() == 1)
        check("в карточке номер и число мест", page.locator(".sheet .field").count() == 2)
        page.locator("#sheet-bg").tap()
        page.wait_for_timeout(500)

        # И перетаскивается.
        at = page.locator(".plan.editing .spot").first.bounding_box()
        field = page.locator(".plan").bounding_box()
        # Тянем в дальнюю половину зала: стол мог остаться где угодно от
        # прошлого прогона, и «вниз» иногда означало «на том же месте».
        middle = field["y"] + field["height"] / 2
        target = field["y"] + field["height"] * (0.85 if at["y"] < middle else 0.15)
        page.mouse.move(at["x"] + at["width"] / 2, at["y"] + at["height"] / 2)
        page.mouse.down()
        page.mouse.move(field["x"] + field["width"] * 0.5, target, steps=15)
        page.mouse.up()
        page.wait_for_timeout(1000)
        after = page.locator(".plan.editing .spot").first.bounding_box()
        check("и перетаскивается пальцем", abs(after["y"] - at["y"]) > 40,
              f"{round(at['y'])} → {round(after['y'])}")

        check("ошибок в консоли нет", not errors, "; ".join(errors[:3]))
        browser.close()

    print()
    if fails:
        print("не прошло:", ", ".join(fails))
        sys.exit(1)
    print("на телефоне работает")


if __name__ == "__main__":
    main()
