#!/usr/bin/env python3
"""Прогон демо-страницы: весь путь смены в одном окне.

Демо (`docs/demo.html`) — не рабочая версия, а стенд: два устройства рядом,
чтобы показать связь «отправил — приехало». Состояние живёт в браузере,
сервер не нужен.

Отдавать файл нужно с явной кодировкой, иначе браузер разберёт кириллицу как
латиницу и страница превратится в «Ð¡Ð¼ÐµÐ½Ð°».
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

CHROME = next(str(p) for p in sorted(Path("/opt/pw-browsers").glob("chromium*/chrome-linux/chrome")))
OUT = Path("/tmp/claude-0/-home-user-menu-for-waiter/064d9f19-630a-5d75-9f7a-e71ed274b08a/scratchpad")
fails = []

def check(name, ok, detail=""):
    print(("  ok  " if ok else " FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok: fails.append(name)

with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path=CHROME, args=["--autoplay-policy=no-user-gesture-required"])
    ctx = b.new_context(viewport={"width":1280,"height":1000}, device_scale_factor=2)
    p = ctx.new_page()
    errs = []
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.goto("http://127.0.0.1:8790/demo.html", wait_until="networkidle")
    p.wait_for_timeout(700)

    check("шрифт меню загрузился", p.evaluate("() => document.fonts.check('16px \"Cormorant Garamond\"')"))
    check("страница не едет вбок", p.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"),
          p.evaluate("() => document.documentElement.scrollWidth + '/' + window.innerWidth"))
    check("экран PIN на телефоне", p.locator("#phone .gate").count() == 1)
    p.screenshot(path=str(OUT/"demo-1.png"), clip={"x":0,"y":0,"width":1280,"height":1000})

    for d in "1111":
        p.locator(f"#phone .pad button[data-key='{d}']").click()
    p.wait_for_timeout(400)
    check("после PIN — план зала", p.locator("#phone .plan .spot").count() == 12,
          str(p.locator("#phone .plan .spot").count()))

    p.locator("#phone .spot[data-table='5']").click(); p.wait_for_timeout(300)
    check("спрашивают гостей", p.locator("#phone .sheet").count() == 1)
    p.locator("#phone [data-open]").click(); p.wait_for_timeout(400)
    check("открылось меню", p.locator("#phone .dish").count() > 0)

    p.locator("#phone .dish[data-add='margh']").click(); p.wait_for_timeout(300)
    check("простое блюдо добавилось одним нажатием", p.locator("#phone .sheet").count() == 0)

    p.locator("#phone .find").fill("водка"); p.wait_for_timeout(300)
    check("поиск по-русски находит английское", p.locator("#phone .dish").count() == 1,
          str(p.locator("#phone .dish").count()))
    p.locator("#phone .dish").first.click(); p.wait_for_timeout(300)
    check("варианты спрашивают", p.locator("#phone .sheet .grp").count() >= 2)
    check("без выбора добавить нельзя", p.locator("#phone [data-confirm][disabled]").count() == 1)
    p.screenshot(path=str(OUT/"demo-2.png"))

    p.locator("#phone .opt[data-pick='size'][data-choice='ml50']").click()
    p.locator("#phone .opt[data-pick='kind'][data-choice='absolut']").click()
    p.wait_for_timeout(200)
    txt = p.locator("#phone [data-confirm]").inner_text()
    check("цена посчиталась", "£13.00" in txt, txt)
    # Микс называет конкретный напиток, а не «микс вообще».
    check("микс предлагает конкретные напитки",
          p.locator("#phone .opt[data-pick='mixer']").count() >= 5,
          str(p.locator("#phone .opt[data-pick='mixer']").count()))
    p.locator("#phone .opt[data-pick='mixer'][data-choice='cola']").click(); p.wait_for_timeout(200)
    txt = p.locator("#phone [data-confirm]").inner_text()
    check("микс прибавил £3", "£16.00" in txt, txt)
    p.locator("#phone .opt[data-pick='mixer'][data-choice='orange']").click(); p.wait_for_timeout(200)
    txt = p.locator("#phone [data-confirm]").inner_text()
    check("второй микс — другой напиток", "£19.00" in txt, txt)
    p.locator("#phone [data-confirm]").click(); p.wait_for_timeout(400)

    p.locator("#phone [data-go='check']").click(); p.wait_for_timeout(400)
    check("в чеке две позиции", p.locator("#phone .line").count() == 2, str(p.locator("#phone .line").count()))
    check("на марке видно, какой именно микс",
          "Микс: Cola" in p.locator("#phone .line").nth(1).inner_text(),
          p.locator("#phone .line").nth(1).inner_text().replace("\n", " "))
    check("на планшете пока пусто", p.locator("#tablet .mark").count() == 0)

    p.locator("#phone [data-send]").click(); p.wait_for_timeout(500)
    check("марки уехали на станции", p.locator("#tablet .mark").count() == 2,
          str(p.locator("#tablet .mark").count()))
    p.screenshot(path=str(OUT/"demo-3.png"))

    bar_mark = p.locator("#tablet .mark").first
    bar_mark.locator("[data-to='accepted']").click(); p.wait_for_timeout(400)
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
    check("станция опустела", p.locator("#tablet .mark").count() == 0)

    p.locator("#phone [data-pay]").click(); p.wait_for_timeout(300)
    check("оплата открылась", p.locator("#phone .sheet").count() == 1)
    p.locator("#phone [data-cash]").click(); p.wait_for_timeout(300)
    p.locator("#phone .opt").nth(1).click(); p.wait_for_timeout(300)
    check("сдача посчиталась", "Сдача" in p.locator("#phone .sheet").inner_text())
    p.locator("#phone [data-close='cash']").click(); p.wait_for_timeout(600)
    check("вернулись к плану зала", p.locator("#phone .plan .spot").count() == 12)

    # админка и перетаскивание
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
    p.screenshot(path=str(OUT/"demo-5.png"))

    p.locator("#theme-phone").click(); p.wait_for_timeout(300)
    check("ночной режим включился", "night" in (p.locator("#phone").get_attribute("class") or ""))
    p.screenshot(path=str(OUT/"demo-6.png"))

    check("ошибок в консоли нет", not errs, "; ".join(errs[:3]))
    b.close()

print()
if fails:
    print("не прошло:", ", ".join(fails)); sys.exit(1)
print("демо работает")
