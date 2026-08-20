#!/usr/bin/env python3
"""Прогон планшета станции в настоящем браузере.

Проверяется главное обещание: официант отправил — на планшете это видно
сразу, без перезагрузки. И второе: когда связь пропала, экран об этом
кричит, а не показывает молча устаревший список.

    python3 tools/check_station.py [http://127.0.0.1:8000]
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
TABLET = {"width": 1180, "height": 820}

fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ok  " if ok else " FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def pin(page, code: str) -> None:
    for digit in code:
        page.get_by_role("button", name=digit, exact=True).click()
    # Экран не принимает нажатия, пока сервер проверяет PIN, — ждём ответа,
    # а не отмеренной паузы.
    page.wait_for_function("() => !Auth.busy", timeout=10000)
    page.wait_for_timeout(700)


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)

        bar_ctx = browser.new_context(viewport=TABLET, has_touch=True)
        bar = bar_ctx.new_page()
        bar_errors: list[str] = []
        bar.on("pageerror", lambda e: bar_errors.append(str(e)))
        bar.goto(BASE + "/station/", wait_until="networkidle")
        pin(bar, "2222")
        check("бармен попадает на свою станцию",
              bar.locator("#title").inner_text().strip().lower() == "бар",
              bar.locator("#title").inner_text())

        waiter_ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
        waiter = waiter_ctx.new_page()
        waiter.goto(BASE, wait_until="networkidle")
        pin(waiter, "1111")

        before = bar.locator(".mark").count()

        waiter.locator(".tile:not(.busy)").first.click()
        waiter.wait_for_timeout(400)
        waiter.get_by_role("button", name="Открыть стол").click()
        waiter.wait_for_timeout(900)
        waiter.locator(".search input").fill("мохито")
        waiter.wait_for_timeout(400)
        waiter.locator(".dish").first.click()
        waiter.wait_for_timeout(500)
        waiter.get_by_role("button", name="К чеку").click()
        waiter.wait_for_timeout(400)
        waiter.get_by_role("button", name="Отправить").click()

        # Ничего не перезагружаем: марка обязана приехать сама.
        bar.wait_for_selector(f".mark >> nth={before}", timeout=6000)
        check("марка пришла сама, без перезагрузки", bar.locator(".mark").count() == before + 1)

        mark = bar.locator(".mark").last
        check("на марке видно стол", mark.locator(".table").inner_text().strip() != "")
        check("на марке видно позицию", "Mojito" in mark.inner_text(), mark.inner_text()[:120])
        check("есть обе кнопки",
              mark.get_by_role("button", name="Принял").count() == 1
              and mark.get_by_role("button", name="Готово").count() == 1)

        mark.get_by_role("button", name="Принял").click()
        bar.wait_for_timeout(900)
        mark = bar.locator(".mark").last
        check("после «Принял» цвет сменился",
              "accepted" in (mark.get_attribute("class") or ""),
              mark.get_attribute("class") or "")
        check("осталась одна кнопка", mark.locator(".mark-foot .btn").count() == 1)

        mark.get_by_role("button", name="Готово").click()
        bar.wait_for_timeout(900)
        mark = bar.locator(".mark").last
        check("готовое ждёт официанта",
              "ждёт официанта" in mark.inner_text().lower(),
              mark.inner_text()[:120])

        # Официант слышит и забирает.
        waiter.wait_for_selector(".ready-item", timeout=6000)
        check("официант видит «готово»", waiter.locator(".ready-item").count() >= 1)
        waiter.get_by_role("button", name="Забрал").first.click()
        waiter.wait_for_timeout(1200)
        check("забранная марка ушла с планшета",
              bar.locator(".mark").count() == before,
              str(bar.locator(".mark").count()))

        # Связь пропала — экран обязан кричать.
        bar_ctx.set_offline(True)
        bar.wait_for_timeout(12000)
        check("потеря связи закрывает экран", bar.locator("#offline").is_visible())
        bar_ctx.set_offline(False)
        bar.wait_for_timeout(4000)
        check("связь вернулась — баннер ушёл", not bar.locator("#offline").is_visible())

        check("ошибок в консоли нет", not bar_errors, "; ".join(bar_errors[:3]))
        browser.close()

    print()
    if fails:
        print("не прошло:", ", ".join(fails))
        sys.exit(1)
    print("станция работает")


if __name__ == "__main__":
    main()
