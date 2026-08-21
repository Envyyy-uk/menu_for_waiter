#!/usr/bin/env python3
"""Табель: смена официанта и итог вечера.

Три вопроса:

1. Идёт ли время с того момента, когда человек открыл смену.
2. Показывается ли итог сразу после закрытия — и не отпускает ли система
   домой с открытым чеком.
3. Попадают ли часы в табель, который смотрит менеджер.

Прогон заводит себе отдельного официанта: у него заведомо нет ни открытой
смены, ни чужих чеков, и повторный запуск не зависит от того, чем кончился
предыдущий.

    python3 tools/check_worktime.py [http://127.0.0.1:8000]
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
DESK = {"width": 1280, "height": 900}

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
    page.wait_for_timeout(700)


# Подписи набраны капителью средствами оформления — сравниваем без учёта
# регистра, иначе проверка ломается от смены шрифта, а не от кода.
def shift_line(page) -> str:
    box = page.locator(".on-shift")
    return box.inner_text().strip().lower() if box.count() else ""


def exit_and_close(page, code: str) -> None:
    """«Выйти» закрывает смену и спрашивает свой PIN."""
    page.locator("#out").click()
    page.wait_for_timeout(600)
    for digit in code:
        page.locator(".sheet .pad button", has_text=digit).first.click()
    page.wait_for_timeout(1200)


def main() -> None:
    code = f"{random.randrange(1000, 9999)}"
    name = f"Смена{random.randrange(100, 999)}"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        errors: list[str] = []

        # --- отдельный официант для прогона -------------------------------
        admin_ctx = browser.new_context(viewport=DESK)
        admin = admin_ctx.new_page()
        admin.on("pageerror", lambda e: errors.append(str(e)))
        admin.goto(BASE + "/admin/", wait_until="networkidle")
        pin(admin, "123456")
        made = admin.evaluate(
            """async ([name, pin]) => {
                const r = await fetch('/api/admin/users', {
                    method: 'POST',
                    headers: { 'content-type': 'application/json' },
                    body: JSON.stringify({ name, role: 'waiter', pin })
                });
                return r.status;
            }""",
            [name, code],
        )
        check("официант для прогона заведён", made == 201, str(made))

        ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until="networkidle")
        pin(page, code)

        # --- смена начинается со входа ------------------------------------
        # Отдельная кнопка «открыть» означала, что однажды её забудут нажать.
        check("смена открылась сама при входе", "смена с" in shift_line(page),
              shift_line(page))
        check("время считается с открытия", "0 мин" in shift_line(page), shift_line(page))

        # --- открытый чек домой не отпускает ------------------------------
        page.locator(FREE_TABLE).first.click()
        page.wait_for_timeout(400)
        page.get_by_role("button", name="Открыть стол").click()
        page.wait_for_timeout(900)
        page.get_by_text("Margherita Pizza", exact=True).click()
        page.wait_for_timeout(500)
        page.get_by_role("button", name="К чеку").click()
        page.wait_for_timeout(500)
        page.get_by_role("button", name="Отправить").click()
        page.wait_for_timeout(900)
        page.get_by_role("button", name="←").click()
        page.wait_for_timeout(800)

        exit_and_close(page, code)
        message = page.locator(".sheet .msg").inner_text()
        check("с открытым чеком смена не закрывается",
              "чек" in message.lower() and "стол" in message.lower(), message)
        page.locator(".sheet .btn.ghost").click()   # выйти, не закрывая
        page.wait_for_timeout(900)
        pin(page, code)
        check("смена всё ещё идёт", "смена с" in shift_line(page), shift_line(page))

        # --- закрыли чек, теперь можно и смену ----------------------------
        page.locator(":is(.spot, .tile).busy").first.click()
        page.wait_for_timeout(900)
        page.get_by_role("button", name="Оплата").click()
        page.wait_for_timeout(600)
        page.locator(".sheet .btn.primary").first.click()      # карта
        page.wait_for_timeout(1500)

        exit_and_close(page, code)
        sheet = page.locator(".sheet").inner_text()
        check("после закрытия показан итог вечера",
              "смена закрыта" in sheet.lower(), sheet.replace("\n", " ")[:120])
        check("в итоге есть отработанное время", "Отработано" in sheet)
        check("в итоге есть выручка и чеки",
              "Выручка" in sheet and "Чеков" in sheet, sheet.replace("\n", " ")[:200])
        check("выручка та, что закрыл сам", "£13.00" in sheet,
              sheet.replace("\n", " ")[:200])
        page.locator(".sheet .btn.primary").last.click()
        page.wait_for_timeout(1200)
        check("после закрытия смены — экран входа",
              page.locator("#gate").count() == 1, page.url)

        # --- часы попали в табель ------------------------------------------
        admin.reload(wait_until="networkidle")
        admin.wait_for_timeout(800)
        admin.locator(".tab", has_text="абел").click()
        admin.wait_for_timeout(900)
        panel = admin.locator(".panel").inner_text()
        check("в табеле есть человек и его часы", name in panel,
              panel.replace("\n", " ")[:200])
        check("видно и часы, и сами смены",
              "Часы" in panel and "Смены" in panel, panel.replace("\n", " ")[:200])

        check("ошибок в консоли нет", not errors, "; ".join(errors[:3]))
        browser.close()

    print()
    if fails:
        print("не прошло:", ", ".join(fails))
        sys.exit(1)
    print("табель работает")


if __name__ == "__main__":
    main()
