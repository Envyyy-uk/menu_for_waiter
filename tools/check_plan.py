#!/usr/bin/env python3
"""Прогон расстановки столов в настоящем браузере.

Проверяется то, ради чего это делалось: управляющий тащит стол мышью, и
официант видит его на новом месте — не в списке координат, а в зале.

    python3 tools/check_plan.py [http://127.0.0.1:8000]
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
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        ctx = browser.new_context(viewport=DESK)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(BASE + "/admin/", wait_until="networkidle")
        pin(page, "1234")
        page.get_by_role("button", name="Столы").click()
        page.wait_for_timeout(900)

        spots = page.locator(".plan .spot")
        check("зал открывается планом, а не таблицей", spots.count() > 0, str(spots.count()))

        first = spots.first
        label = first.locator(".n").inner_text()
        before = first.bounding_box()

        # Тащим стол в противоположный угол — именно в противоположный, иначе
        # прогон, запущенный дважды, «переносит» стол туда, где он уже стоит.
        plan = page.locator(".plan").first.bounding_box()
        was_left = (before["x"] + before["width"] / 2 - plan["x"]) / plan["width"] < 0.5
        target_x = 0.82 if was_left else 0.16
        page.mouse.move(before["x"] + before["width"] / 2, before["y"] + before["height"] / 2)
        page.mouse.down()
        page.mouse.move(plan["x"] + plan["width"] * target_x,
                        plan["y"] + plan["height"] * 0.75, steps=12)
        page.mouse.up()
        page.wait_for_timeout(1200)

        after = page.locator(f".plan .spot:has(.n:text-is('{label}'))").bounding_box()
        check("стол переехал", abs(after["x"] - before["x"]) > 100,
              f"{round(before['x'])} → {round(after['x'])}")

        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1200)
        page.get_by_role("button", name="Столы").click()
        page.wait_for_timeout(900)
        kept = page.locator(f".plan .spot:has(.n:text-is('{label}'))").bounding_box()
        check("и остался там после перезагрузки", abs(kept["x"] - after["x"]) < 20,
              f"{round(after['x'])} → {round(kept['x'])}")

        # Номер стола меняется на месте.
        page.locator(f".plan .spot:has(.n:text-is('{label}'))").click()
        page.wait_for_timeout(500)
        check("нажатие открывает карточку стола", page.locator(".sheet").is_visible())
        page.locator(".sheet .field").first.fill("VIP")
        page.get_by_role("button", name="Сохранить").click()
        page.wait_for_timeout(1200)
        check("номер поменялся",
              page.locator(".plan .spot:has(.n:text-is('VIP'))").count() == 1)

        # Официант видит ту же расстановку.
        waiter_ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
        waiter = waiter_ctx.new_page()
        waiter.goto(BASE, wait_until="networkidle")
        pin(waiter, "1111")
        check("официант видит зал планом", waiter.locator(".plan .spot").count() > 0)
        check("и новый номер стола",
              waiter.locator(".plan .spot:has(.n:text-is('VIP'))").count() == 1)

        # Не «столы есть», а «столы стоят там, где их поставили». Без этой
        # проверки они однажды все окажутся в левом верхнем углу друг на
        # друге — сетка зала есть, расстановки нет.
        field = waiter.locator(".plan").first.bounding_box()
        moved = waiter.locator(".plan .spot:has(.n:text-is('VIP'))").bounding_box()
        share_x = (moved["x"] + moved["width"] / 2 - field["x"]) / field["width"]
        share_y = (moved["y"] + moved["height"] / 2 - field["y"]) / field["height"]
        low, high = (0.72, 0.92) if was_left else (0.06, 0.26)
        check("и стоит там, куда его поставили",
              low < share_x < high and 0.6 < share_y < 0.9,
              f"{share_x:.2f} / {share_y:.2f}")

        spread = set()
        for n in range(waiter.locator(".plan .spot").count()):
            box = waiter.locator(".plan .spot").nth(n).bounding_box()
            spread.add((round(box["x"]), round(box["y"])))
        check("столы не лежат друг на друге",
              len(spread) == waiter.locator(".plan .spot").count(), str(len(spread)))

        # И не может ничего сдвинуть.
        vip = waiter.locator(".plan .spot:has(.n:text-is('VIP'))")
        was = vip.bounding_box()
        waiter.mouse.move(was["x"] + was["width"] / 2, was["y"] + was["height"] / 2)
        waiter.mouse.down()
        waiter.mouse.move(was["x"] + 90, was["y"] + 60, steps=8)
        waiter.mouse.up()
        waiter.wait_for_timeout(800)
        now = waiter.locator(".plan .spot:has(.n:text-is('VIP'))").bounding_box()
        check("официант не может передвинуть стол", abs(now["x"] - was["x"]) < 5,
              f"{round(was['x'])} → {round(now['x'])}")

        # Возвращаем номер, чтобы прогон можно было повторить.
        page.locator(".plan .spot:has(.n:text-is('VIP'))").click()
        page.wait_for_timeout(400)
        page.locator(".sheet .field").first.fill(label)
        page.get_by_role("button", name="Сохранить").click()
        page.wait_for_timeout(900)

        check("ошибок в консоли нет", not errors, "; ".join(errors[:3]))
        browser.close()

    print()
    if fails:
        print("не прошло:", ", ".join(fails))
        sys.exit(1)
    print("расстановка работает")


if __name__ == "__main__":
    main()
