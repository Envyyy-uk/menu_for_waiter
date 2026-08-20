#!/usr/bin/env python3
"""Прогон демо-страницы: полный путь смены плюс два стола рядом.

Демо (`docs/demo.html`) — не рабочая версия, а стенд: два устройства рядом,
чтобы показать связь «отправил — приехало». Состояние живёт в браузере.

Отдавать файл нужно с явной кодировкой, иначе браузер разберёт кириллицу как
латиницу и страница превратится в «Ð¡Ð¼ÐµÐ½Ð°».
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

CHROME = next(str(p) for p in sorted(Path("/opt/pw-browsers").glob("chromium*/chrome-linux/chrome")))
OUT = Path("/tmp/claude-0/-home-user-menu-for-waiter/064d9f19-630a-5d75-9f7a-e71ed274b08a/scratchpad")
BASE = "http://127.0.0.1:8790/demo.html"
fails = []

def check(name, ok, detail=""):
    print(("  ok  " if ok else " FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok: fails.append(name)

def enter(p, pin="1111"):
    for d in pin:
        p.locator(f"#phone .pad button[data-key='{d}']").click()
    p.wait_for_timeout(300)

def open_table(p, n, guests_taps=0):
    p.locator(f"#phone .spot[data-table='{n}']").click(); p.wait_for_timeout(300)
    for _ in range(guests_taps):
        p.locator("#phone [data-guests='1']").click()
    p.locator("#phone [data-open]").click(); p.wait_for_timeout(400)

def add(p, key):
    p.locator(f"#phone .dish[data-add='{key}']").click(); p.wait_for_timeout(300)

def to_check(p):
    p.locator("#phone [data-go='check']").click(); p.wait_for_timeout(300)

def title(p):
    # Заголовок набран капителью средствами оформления — сравниваем без
    # учёта регистра, иначе проверка ломается от смены шрифта.
    return p.locator("#phone .bar h3").inner_text().lower()


def back_to_tables(p):
    p.locator("#phone .bar [data-back]").click(); p.wait_for_timeout(300)

with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path=CHROME, args=["--autoplay-policy=no-user-gesture-required"])
    ctx = b.new_context(viewport={"width":1280,"height":1000}, device_scale_factor=2)
    p = ctx.new_page()
    errs = []
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto(BASE, wait_until="networkidle")
    p.wait_for_timeout(700)

    check("шрифт меню загрузился", p.evaluate("() => document.fonts.check('16px \"Cormorant Garamond\"')"))
    check("страница не едет вбок", p.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"))
    check("экран PIN на телефоне", p.locator("#phone .gate").count() == 1)
    p.screenshot(path=str(OUT/"demo-1.png"))

    enter(p)
    check("после PIN — план зала", p.locator("#phone .plan .spot").count() == 12)

    # ---- два стола рядом: то, на чём демо ломалось -------------------------
    open_table(p, 5)
    add(p, "margh")
    to_check(p)
    check("стол 5: чек открылся", "стол 5" in title(p), title(p))
    back_to_tables(p)

    open_table(p, 9)
    add(p, "mojito")
    to_check(p)
    check("стол 9 открыл СВОЙ чек, а не пятый", "стол 9" in title(p), title(p))
    check("в чеке стола 9 только его позиция",
          p.locator("#phone .line").count() == 1
          and "Mojito" in p.locator("#phone .line").inner_text(),
          p.locator("#phone .line").inner_text().replace("\n", " "))
    back_to_tables(p)

    check("оба стола заняты", p.locator("#phone .spot.busy").count() == 2,
          str(p.locator("#phone .spot.busy").count()))
    sums = p.locator("#phone .spot.busy .sum").all_inner_texts()
    check("суммы у столов разные", sorted(sums) == ["£13.00", "£16.00"], str(sums))

    # Возвращаемся в первый — он не должен подменяться вторым.
    p.locator("#phone .spot[data-table='5']").click(); p.wait_for_timeout(400)
    check("возврат к столу 5 открывает его чек",
          "стол 5" in title(p) and "Margherita" in p.locator("#phone .line").inner_text(),
          title(p))
    p.screenshot(path=str(OUT/"demo-2.png"))

    # ---- варианты и микс ---------------------------------------------------
    p.locator("#phone [data-go='menu']").click(); p.wait_for_timeout(300)
    p.locator("#phone .find").fill("водка"); p.wait_for_timeout(300)
    check("поиск по-русски находит английское", p.locator("#phone .dish").count() == 1,
          str(p.locator("#phone .dish").count()))
    p.locator("#phone .dish").first.click(); p.wait_for_timeout(300)
    check("без выбора добавить нельзя", p.locator("#phone [data-confirm][disabled]").count() == 1)
    p.locator("#phone .opt[data-pick='size'][data-choice='ml50']").click()
    p.locator("#phone .opt[data-pick='kind'][data-choice='absolut']").click()
    p.wait_for_timeout(200)
    check("цена посчиталась", "£13.00" in p.locator("#phone [data-confirm]").inner_text(),
          p.locator("#phone [data-confirm]").inner_text())
    check("микс предлагает конкретные напитки",
          p.locator("#phone .opt[data-pick='mixer']").count() >= 5)
    p.locator("#phone .opt[data-pick='mixer'][data-choice='cola']").click(); p.wait_for_timeout(200)
    p.locator("#phone .opt[data-pick='mixer'][data-choice='orange']").click(); p.wait_for_timeout(200)
    check("два разных микса — плюс £6", "£19.00" in p.locator("#phone [data-confirm]").inner_text(),
          p.locator("#phone [data-confirm]").inner_text())
    p.screenshot(path=str(OUT/"demo-3.png"))
    p.locator("#phone [data-confirm]").click(); p.wait_for_timeout(400)
    to_check(p)
    check("на марке видно, какой именно микс",
          "Микс: Cola" in p.locator("#phone .line").nth(1).inner_text(),
          p.locator("#phone .line").nth(1).inner_text().replace("\n", " "))

    # ---- отправка и станция ------------------------------------------------
    check("на планшете пока пусто", p.locator("#tablet .mark").count() == 0)
    p.locator("#phone [data-send]").click(); p.wait_for_timeout(500)
    check("марки уехали на станции", p.locator("#tablet .mark").count() == 2,
          str(p.locator("#tablet .mark").count()))
    check("на марке виден номер стола",
          "5" in p.locator("#tablet .mark").first.locator(".t").inner_text())

    bar_first = p.locator("#tablet .mark").first
    bar_first.locator("[data-to='accepted']").click(); p.wait_for_timeout(400)
    check("«Принял» сменил вид марки", "accepted" in (p.locator("#tablet .mark").first.get_attribute("class") or ""))
    p.locator("#tablet .mark").first.locator("[data-to='ready']").click(); p.wait_for_timeout(500)
    check("официант увидел «готово»", p.locator("#phone .ready-row").count() == 1)
    check("вторая станция ещё в работе",
          p.locator("#tablet .mark").nth(1).locator("[data-to='ready']").count() == 1)
    p.screenshot(path=str(OUT/"demo-4.png"))

    p.locator("#phone [data-take]").click(); p.wait_for_timeout(400)
    check("забрал — полоса ушла", p.locator("#phone .ready-row").count() == 0)
    p.locator("#tablet .mark").first.locator("[data-to='ready']").click(); p.wait_for_timeout(400)
    p.locator("#phone [data-take]").click(); p.wait_for_timeout(400)
    check("станция опустела по этому чеку", p.locator("#tablet .mark").count() == 0)

    # ---- оплата ------------------------------------------------------------
    p.locator("#phone [data-pay]").click(); p.wait_for_timeout(300)
    p.locator("#phone [data-cash]").click(); p.wait_for_timeout(300)
    p.locator("#phone .sheet .opt").nth(1).click(); p.wait_for_timeout(300)
    check("сдача посчиталась", "Сдача" in p.locator("#phone .sheet").inner_text())
    p.locator("#phone [data-close='cash']").click(); p.wait_for_timeout(600)
    check("вернулись к плану зала", p.locator("#phone .plan .spot").count() == 12)
    check("закрылся только один стол", p.locator("#phone .spot.busy").count() == 1,
          str(p.locator("#phone .spot.busy").count()))
    check("второй стол цел",
          p.locator("#phone .spot[data-table='9'] .sum").inner_text() == "£16.00",
          p.locator("#phone .spot[data-table='9'] .sum").inner_text())

    # ---- два чека на одном столе -------------------------------------------
    # Компания делится, и второй чек нужен прямо из первого: занятый стол в
    # сетке сразу открывает свой чек, и это правильно.
    p.locator("#phone .spot[data-table='9']").click(); p.wait_for_timeout(400)
    first_number = title(p)
    p.locator("#phone [data-split]").click(); p.wait_for_timeout(300)
    p.locator("#phone [data-open]").click(); p.wait_for_timeout(400)
    add(p, "cheese")
    to_check(p)
    check("второй чек на том же столе — отдельный",
          title(p) != first_number and "стол 9" in title(p),
          f"{first_number} → {title(p)}")
    check("в нём только своя позиция",
          p.locator("#phone .line").count() == 1
          and "Cheesecake" in p.locator("#phone .line").inner_text(),
          p.locator("#phone .line").inner_text().replace("\n", " "))

    back_to_tables(p)
    p.locator("#phone .spot[data-table='9']").click(); p.wait_for_timeout(400)
    check("теперь стол 9 спрашивает, какой из двух чеков",
          p.locator("#phone .sheet [data-check]").count() == 2,
          str(p.locator("#phone .sheet [data-check]").count()))
    p.locator("#phone .sheet [data-check]").first.click(); p.wait_for_timeout(400)
    check("выбранный чек и открылся",
          "Mojito" in p.locator("#phone .line").inner_text(),
          p.locator("#phone .line").inner_text().replace("\n", " "))
    back_to_tables(p)

    # ---- админка и перетаскивание -------------------------------------------
    p.locator("[data-right='admin']").click(); p.wait_for_timeout(400)
    check("админка открылась", p.locator("#tablet .plan.edit .spot").count() == 12)
    spot = p.locator("#tablet .spot[data-move='5']")
    before = spot.bounding_box()
    field = p.locator("#tablet .plan").bounding_box()
    p.mouse.move(before["x"]+before["width"]/2, before["y"]+before["height"]/2)
    p.mouse.down()
    p.mouse.move(field["x"]+field["width"]*0.5, field["y"]+field["height"]*0.85, steps=10)
    p.mouse.up(); p.wait_for_timeout(400)
    after = p.locator("#phone .spot[data-table='5']").bounding_box()
    phone_field = p.locator("#phone .plan").bounding_box()
    share_y = (after["y"]+after["height"]/2 - phone_field["y"]) / phone_field["height"]
    check("телефон показал новую расстановку", share_y > 0.7, f"{share_y:.2f}")

    # ---- сброс --------------------------------------------------------------
    p.locator("#reset").click(); p.wait_for_timeout(400)
    check("«Заново» вернуло к вводу PIN", p.locator("#phone .gate").count() == 1)
    enter(p)
    check("после сброса столы свободны", p.locator("#phone .spot.busy").count() == 0,
          str(p.locator("#phone .spot.busy").count()))
    check("расстановка после сброса сохранилась",
          abs(p.locator("#phone .spot[data-table='5']").bounding_box()["y"] - after["y"]) < 6)

    p.locator("#theme-phone").click(); p.wait_for_timeout(300)
    check("ночной режим включился", "night" in (p.locator("#phone").get_attribute("class") or ""))
    p.screenshot(path=str(OUT/"demo-5.png"))

    check("ошибок в консоли нет", not errs, "; ".join(errs[:3]))
    b.close()

print()
if fails:
    print("не прошло:", ", ".join(fails)); sys.exit(1)
print("демо работает")
