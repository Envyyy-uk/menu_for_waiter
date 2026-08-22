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

def station_pin(p, pin="2468"):
    for d in pin:
        p.locator(f"#tablet .pad button[data-skey='{d}']").click()
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

    # ---- смена на планшете станции -----------------------------------------
    # Планшет живёт отдельно от личных входов: пока смена не открыта, на нём
    # нет ничего, даже если официант уже вошёл.
    check("планшет без смены просит PIN станции", p.locator("#tablet .gate").count() == 1)
    station_pin(p, "1357")
    check("чужой PIN смену не открывает",
          p.locator("#tablet .gate").count() == 1
          and "не подходит" in p.locator("#tablet .gate .hint").inner_text().lower(),
          p.locator("#tablet .gate .hint").inner_text())
    station_pin(p)
    check("PIN станции открыл смену", p.locator("#tablet .board-grid").count() == 1)
    check("смена по PIN станции остаётся без имени",
          "игорь" not in p.locator("#tablet .bar .who").inner_text().lower(),
          p.locator("#tablet .bar .who").inner_text())

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

    # ---- склад --------------------------------------------------------------
    # Списание идёт на отправке, а не на закрытии чека: чек ещё не оплачен,
    # а продукт уже налит.
    p.locator("[data-right='stock']").click(); p.wait_for_timeout(400)
    stock = p.locator("#tablet .view").inner_text()
    check("с бутылки ушло ровно налитое", "650 мл" in stock, stock.replace("\n", " ")[:160])
    check("банка микса списалась отдельно", "4 шт" in stock, stock.replace("\n", " ")[:160])
    check("кухня списала своё", "880 г" in stock, stock.replace("\n", " ")[:160])
    check("видно, что это продажа и кто отправил",
          "продажа" in stock and "Аня" in stock)
    check("«мало» показано тревогой", p.locator("#tablet .alarm").count() == 1
          and "Cola" in p.locator("#tablet .alarm").inner_text(),
          stock.replace("\n", " ")[:160])
    p.screenshot(path=str(OUT/"demo-6.png"))
    p.locator("[data-right='station']").click(); p.wait_for_timeout(300)

    # ---- скидка перед оплатой -----------------------------------------------
    # Скидку дают до того, как назвали сумму: после закрытия чек уже документ.
    p.locator("#phone [data-pay]").click(); p.wait_for_timeout(300)
    p.locator("#phone [data-disc]").click(); p.wait_for_timeout(300)
    p.locator("#phone .sheet .opt[data-pc='10']").click(); p.wait_for_timeout(300)
    check("процент посчитан от позиций",
          "£3.20" in p.locator("#phone .sheet").inner_text(),
          p.locator("#phone .sheet").inner_text().replace("\n", " ")[:140])
    p.locator("#phone #why").fill("ждали долго"); p.wait_for_timeout(200)
    p.locator("#phone [data-setdisc='1']").click(); p.wait_for_timeout(500)
    check("к оплате уменьшилось",
          "£28.80" in p.locator("#phone .sheet").inner_text(),
          p.locator("#phone .sheet").inner_text().replace("\n", " ")[:140])

    # ---- оплата ------------------------------------------------------------
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

    # ---- оплаты: за что именно взяли деньги ---------------------------------
    p.locator("[data-right='paid']").click(); p.wait_for_timeout(400)
    paid = p.locator("#tablet .view").inner_text()
    check("закрытый чек попал в оплаты", "наличные" in paid, paid.replace("\n", " ")[:160])
    check("скидка видна с причиной",
          "−£3.20" in paid and "ждали долго" in paid, paid.replace("\n", " ")[:200])
    check("видно, что было внутри", "Margherita" in paid, paid.replace("\n", " ")[:200])
    check("итог сходится", "£28.80" in paid, paid.replace("\n", " ")[:200])
    p.screenshot(path=str(OUT/"demo-7.png"))
    p.locator("[data-right='station']").click(); p.wait_for_timeout(300)

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

    # ---- смена именем человека ----------------------------------------------
    # Планшет один, а барменов за вечер двое. Личный PIN пишет в смену имя,
    # и закрыть её может второй: смену сдают.
    p.locator("[data-right='station']").click(); p.wait_for_timeout(300)
    check("после сброса планшет снова просит PIN", p.locator("#tablet .gate").count() == 1)
    station_pin(p, "2222")
    check("личный PIN бармена открыл смену", p.locator("#tablet .board-grid").count() == 1)
    check("в шапке смены стоит имя",
          "игорь" in p.locator("#tablet .bar .who").inner_text().lower(),
          p.locator("#tablet .bar .who").inner_text())

    # На баре двое: смена одна — очередь марок общая, — но имён в ней два.
    p.locator("#tablet [data-shift='join']").click(); p.wait_for_timeout(300)
    station_pin(p, "2468")
    check("общий PIN в смену никого не записывает",
          "личный" in p.locator("#tablet .gate .hint").inner_text().lower(),
          p.locator("#tablet .gate .hint").inner_text())
    station_pin(p, "2727")
    who = p.locator("#tablet .bar .who").inner_text().lower()
    check("второй бармен встал в ту же смену", "игорь" in who and "слава" in who, who)
    check("часы идут у каждого свои", who.count("мин") + who.count(" ч ") >= 2, who)
    check("смена осталась одна", p.locator("#tablet .board-grid").count() == 1)
    check("кнопка обещает уход, а не закрытие",
          "уйти" in p.locator("#tablet [data-shift='close']").inner_text().lower(),
          p.locator("#tablet [data-shift='close']").inner_text())

    # Ушёл домой раньше — планшет работает дальше: очередь марок общая, и
    # погасить её значит оставить второго без заказов.
    p.locator("#tablet [data-shift='close']").click(); p.wait_for_timeout(300)
    station_pin(p, "2222")
    p.wait_for_timeout(400)
    who = p.locator("#tablet .bar .who").inner_text().lower()
    check("ушедший пропал из шапки", "игорь" not in who and "слава" in who, who)
    check("смена не закрылась", p.locator("#tablet .board-grid").count() == 1)
    check("остался один — кнопка снова про закрытие",
          "закрыть" in p.locator("#tablet [data-shift='close']").inner_text().lower(),
          p.locator("#tablet [data-shift='close']").inner_text())
    # Игорь вернулся: смена та же, и в шапке снова двое.
    p.locator("#tablet [data-shift='join']").click(); p.wait_for_timeout(300)
    station_pin(p, "2222")
    p.wait_for_timeout(400)
    who = p.locator("#tablet .bar .who").inner_text().lower()
    check("вернувшийся снова в шапке", "игорь" in who and "слава" in who, who)
    # И ушёл уже до конца вечера — дальше Слава один.
    p.locator("#tablet [data-shift='close']").click(); p.wait_for_timeout(300)
    station_pin(p, "2222")
    p.wait_for_timeout(400)
    p.locator("#phone .spot[data-table='3']").click(); p.wait_for_timeout(300)
    p.locator("#phone [data-open]").click(); p.wait_for_timeout(300)
    add(p, "pelmeni")
    to_check(p)
    p.locator("#phone [data-send]").click(); p.wait_for_timeout(400)
    p.locator("#tablet .mark").first.locator("[data-to='ready']").click(); p.wait_for_timeout(400)

    p.locator("#tablet [data-shift='close']").click(); p.wait_for_timeout(300)
    check("закрытие смены тоже просит PIN",
          p.locator("#tablet .gate").count() == 1
          and "закрыт" in p.locator("#tablet .bar h3").inner_text().lower(),
          p.locator("#tablet .bar h3").inner_text())
    station_pin(p, "1357")
    check("чужим PIN смену не закрыть", p.locator("#tablet .gate").count() == 1)
    station_pin(p, "2727")
    toast = p.locator("#tablet .toast").inner_text().lower()
    check("смена закрылась и посчитала марки", "1 марка" in toast, toast)
    check("закрыл смену второй бармен — и это видно", "слава" in toast, toast)
    check("после закрытия планшет снова просит PIN", p.locator("#tablet .gate").count() == 1)

    # ---- личная смена официанта ---------------------------------------------
    # Табель: пришёл — открыл, ушёл — закрыл. Часы идут сами.
    back_to_tables(p)
    p.locator("#phone [data-work='open']").click(); p.wait_for_timeout(1600)
    closer = p.locator("#phone [data-work='close']")
    check("смена официанта открылась и считает время", closer.count() == 1,
          p.locator("#phone .worker").inner_text())
    check("время идёт", "мин" in closer.inner_text(), closer.inner_text())

    # На столе 3 остался чек — с ним домой не уходят.
    closer.click(); p.wait_for_timeout(400)
    check("с открытым чеком смена не закрывается",
          "стол 3" in p.locator("#phone .toast").inner_text().lower(),
          p.locator("#phone .toast").inner_text())

    p.locator("#phone .spot[data-table='3']").click(); p.wait_for_timeout(500)
    p.locator("#phone [data-pay]").click(); p.wait_for_timeout(300)
    p.locator("#phone [data-close='card']").click(); p.wait_for_timeout(800)
    p.locator("#phone [data-work='close']").click(); p.wait_for_timeout(500)
    sheet = p.locator("#phone .sheet").inner_text()
    check("после закрытия показан итог смены",
          "смена закрыта" in sheet.lower() and "Отработано" in sheet,
          sheet.replace("\n", " ")[:140])
    check("в итоге есть выручка и чеки",
          "Выручка" in sheet and "Чеков" in sheet, sheet.replace("\n", " ")[:200])
    p.screenshot(path=str(OUT/"demo-work.png"))
    p.locator("#phone [data-veil]").last.click(); p.wait_for_timeout(400)
    check("смена закрыта — кнопка снова «открыть»",
          p.locator("#phone [data-work='open']").count() == 1)

    # ---- столы пачкой --------------------------------------------------------
    p.locator("[data-right='admin']").click(); p.wait_for_timeout(400)
    was = p.locator("#tablet .plan.edit .spot").count()
    p.locator("#tablet [data-tables='4']").click(); p.wait_for_timeout(600)
    check("четыре стола встали одной кнопкой",
          p.locator("#tablet .plan.edit .spot").count() == was + 4,
          str(p.locator("#tablet .plan.edit .spot").count()))
    check("телефон увидел новые столы сразу",
          p.locator("#phone .spot").count() == was + 4,
          str(p.locator("#phone .spot").count()))
    p.locator("#tablet [data-tables='-1']").click(); p.wait_for_timeout(500)
    check("и убираются обратно",
          p.locator("#tablet .plan.edit .spot").count() == was + 3)
    p.locator("[data-right='station']").click(); p.wait_for_timeout(300)

    p.locator("#theme-phone").click(); p.wait_for_timeout(300)
    check("ночной режим включился", "night" in (p.locator("#phone").get_attribute("class") or ""))
    p.screenshot(path=str(OUT/"demo-5.png"))

    # ---- демо не убегает из-под пальца ---------------------------------------
    # Экран собирается заново на каждое нажатие. Если при этом теряется
    # прокрутка, страница прыгает к заголовку, а список меню — к первой
    # позиции; проверить в таком демо нельзя ничего.
    phone = ctx2 = None
    small = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    phone = small.new_page()
    phone.goto(BASE, wait_until="networkidle")
    phone.wait_for_timeout(500)
    for d in "1111":
        phone.locator(f"#phone .pad button[data-key='{d}']").click()
    phone.wait_for_timeout(400)
    for d in "2468":
        phone.locator(f"#tablet .pad button[data-skey='{d}']").click()
    phone.wait_for_timeout(400)

    phone.evaluate("() => document.querySelector('#phone .spot').click()")
    phone.wait_for_timeout(300)
    phone.evaluate("() => document.querySelector('#phone [data-open]').click()")
    phone.wait_for_timeout(500)

    # Список меню длинный: прокручиваем и добавляем позицию.
    phone.evaluate("() => document.querySelector('#phone .view').scrollTop = 260")
    phone.wait_for_timeout(200)
    before_list = phone.evaluate("() => document.querySelector('#phone .view').scrollTop")
    # Нажимаем через DOM: playwright сам подкручивает элемент в вид, а
    # проверяем мы здесь как раз прокрутку.
    phone.evaluate("() => document.querySelector(\"#phone .dish[data-add='margh']\").click()")
    phone.wait_for_timeout(500)
    after_list = phone.evaluate("() => document.querySelector('#phone .view').scrollTop")
    check("список меню остаётся на месте после добавления",
          before_list > 100 and abs(after_list - before_list) < 30,
          f"{before_list} → {after_list}")

    # Страница целиком: уехали к планшету, нажали — остались там же.
    phone.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    phone.wait_for_timeout(300)
    before_page = phone.evaluate("() => window.pageYOffset")
    phone.evaluate("() => document.querySelector(\"#phone [data-go='check']\").click()")
    phone.wait_for_timeout(500)
    after_page = phone.evaluate("() => window.pageYOffset")
    check("страница не прыгает к заголовку",
          before_page > 200 and abs(after_page - before_page) < 30,
          f"{before_page} → {after_page}")
    phone.screenshot(path=str(OUT/"demo-phone.png"), full_page=False)
    small.close()

    check("ошибок в консоли нет", not errs, "; ".join(errs[:3]))
    b.close()

print()
if fails:
    print("не прошло:", ", ".join(fails)); sys.exit(1)
print("демо работает")
