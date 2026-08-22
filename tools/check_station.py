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

# Зал рисуется планом, а сетка осталась запасным видом — когда
# расстановки ещё нет. Проверки ищут стол в обоих.
FREE_TABLE = ":is(.spot, .tile):not(.busy)"
BUSY_TABLE = ":is(.spot, .tile).busy"
TABLE_NUMBER = ":is(.n, .num)"
HALL = ":is(.plan, .tables)"

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


def station_pin(page, code: str) -> None:
    """PIN планшета: у него свой экран, без личных имён."""
    for digit in code:
        page.locator("#pin-pad button", has_text=digit).first.click()
    page.wait_for_timeout(1500)


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)

        # PIN станции задаёт администратор — планшет к личным входам не
        # обращается вовсе.
        admin_ctx = browser.new_context(viewport=TABLET)
        admin = admin_ctx.new_page()
        admin.goto(BASE + "/admin/", wait_until="networkidle")
        pin(admin, "123456")
        admin.get_by_role("button", name="Станции").click()
        admin.wait_for_timeout(900)
        row = admin.locator("tr", has_text="Бар").first
        row.locator("button").first.click()
        admin.wait_for_timeout(500)
        admin.locator(".sheet .field").fill("5555")
        admin.get_by_role("button", name="Сохранить").click()
        admin.wait_for_timeout(1000)
        check("PIN станции задаётся в админке",
              "задан" in admin.locator("tr", has_text="Бар").first.inner_text(),
              admin.locator("tr", has_text="Бар").first.inner_text())

        bar_ctx = browser.new_context(viewport=TABLET, has_touch=True)
        bar = bar_ctx.new_page()
        bar_errors: list[str] = []
        bar.on("pageerror", lambda e: bar_errors.append(str(e)))
        bar.goto(BASE + "/station/", wait_until="networkidle")
        bar.wait_for_timeout(800)
        check("планшет без смены спрашивает PIN станции",
              bar.locator("#gate").is_visible() and bar.locator(".mark").count() == 0)

        # Смену открывает бармен своим PIN: планшет один, а барменов за вечер
        # двое, и «смену открыл планшет» — ответ, который ничего не стоит.
        station_pin(bar, "2222")
        check("смена открылась своей станцией",
              bar.locator("#title").inner_text().strip().lower() == "бар",
              bar.locator("#title").inner_text())
        check("в шапке видно время открытия смены",
              "смена с" in bar.locator("#who").inner_text(),
              bar.locator("#who").inner_text())
        check("в шапке стоит имя того, кто открыл",
              "Игорь" in bar.locator("#who").inner_text(),
              bar.locator("#who").inner_text())

        # На баре двое: смена одна — очередь марок общая, — но имён в ней два.
        bar.get_by_role("button", name="Ещё человек").click()
        bar.wait_for_timeout(500)
        station_pin(bar, "5555")
        check("общий PIN станции в смену никого не записывает",
              bar.locator("#gate").is_visible())
        station_pin(bar, "3333")
        check("кухня в смену бара не встаёт", bar.locator("#gate").is_visible())
        station_pin(bar, "2727")
        bar.wait_for_timeout(800)
        who = bar.locator("#who").inner_text()
        check("второй встал в ту же смену",
              "Игорь" in who and "Слава" in who and not bar.locator("#gate").is_visible(),
              who)
        # Часы каждому от его прихода: один встал в шесть, другой в девять, и
        # платить обоим по большему — чужие деньги.
        check("у каждого свои часы", who.count("мин") >= 2, who)

        waiter_ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
        waiter = waiter_ctx.new_page()
        waiter.goto(BASE, wait_until="networkidle")
        pin(waiter, "1111")

        before = bar.locator(".mark").count()

        waiter.locator(FREE_TABLE).first.click()
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

        # Пока на баре двое, кнопка обещает уход, а не закрытие: ушедший
        # домой раньше не гасит планшет за тем, кто остался работать.
        check("кнопка обещает уход, а не закрытие",
              "Уйти" in bar.locator("#out").inner_text(),
              bar.locator("#out").inner_text())
        bar.locator("#out").click()
        bar.wait_for_timeout(500)
        station_pin(bar, "2222")
        bar.wait_for_timeout(900)
        who = bar.locator("#who").inner_text()
        check("ушедший пропал из шапки", "Игорь" not in who and "Слава" in who, who)
        check("ушедшему показали его часы",
              "Со смены" in bar.locator(".toast").inner_text(),
              bar.locator(".toast").inner_text())
        check("планшет остался работать",
              not bar.locator("#gate").is_visible() and bar.locator(".mark").count() >= 1)
        check("остался один — кнопка снова про закрытие",
              "Закрыть" in bar.locator("#out").inner_text(),
              bar.locator("#out").inner_text())

        # Закрывается смена PIN-ом — своим или станции. PIN станции здесь и
        # проверяется: он запасной вход на случай забытого личного.
        bar.get_by_role("button", name="Закрыть смену").click()
        bar.wait_for_timeout(600)
        check("закрытие смены тоже просит PIN", bar.locator("#gate").is_visible())
        station_pin(bar, "0000")
        check("чужой PIN смену не закрывает",
              "PIN" in bar.locator("#pin-msg").inner_text(),
              bar.locator("#pin-msg").inner_text())
        station_pin(bar, "5555")
        bar.wait_for_timeout(2500)
        check("после закрытия планшет снова просит PIN", bar.locator("#gate").is_visible())
        station_pin(bar, "5555")

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
