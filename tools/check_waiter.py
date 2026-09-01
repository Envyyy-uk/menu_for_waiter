#!/usr/bin/env python3
"""Прогон приложения официанта в настоящем браузере.

Тесты API говорят, что сервер считает правильно. Здесь другой вопрос: может
ли официант с телефона в руке пройти путь от пустого стола до закрытого чека,
ни разу не застряв.

    python3 tools/check_waiter.py [http://127.0.0.1:8000]
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
    page.wait_for_function("() => !Auth.busy", timeout=10000)
    page.wait_for_timeout(700)


def money(pence: int) -> str:
    """Как это пишет само приложение: £26.00."""
    return f"£{pence / 100:.2f}"


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(BASE, wait_until="networkidle")
        pin(page, "1111")
        check("официант попадает на столы", page.locator(HALL).count() > 0, page.url)

        free = page.locator(FREE_TABLE).first
        label = free.locator(TABLE_NUMBER).inner_text()
        free.click()
        page.wait_for_timeout(400)
        check("спрашивают число гостей", page.locator(".sheet").is_visible())
        page.get_by_role("button", name="+").click()
        page.get_by_role("button", name="Открыть стол").click()
        page.wait_for_timeout(900)
        check("после открытия сразу меню", page.locator(".dish").count() > 0)

        # Позиция без вариантов — одно нажатие, без лишнего экрана.
        #
        # Позицию не называем: что продаётся, решает сайт меню, а не прогон.
        # Раздел, помеченный там «скоро», в зале продавать нельзя — и когда
        # кухню на сайте выключили, прогон падал на «пицце не добавляется»,
        # хотя приложение вело себя ровно так, как должно.
        simple = page.evaluate("""() => {
            const i = (App.menu.items || []).find(
                x => x.state === 'on' && !(x.options || []).length);
            return i ? {name: i.name, price: i.price_pence} : null;
        }""")
        check("в меню есть что продать без вариантов", simple is not None)
        page.get_by_text(simple["name"], exact=True).first.click()
        page.wait_for_timeout(600)
        check("простая позиция добавляется одним нажатием",
              not page.locator(".sheet").is_visible())

        # Позиция с вариантами — шторка, и без выбора добавить нельзя.
        page.locator(".search input").fill("водка")
        page.wait_for_timeout(400)
        check("поиск по-русски находит английское название",
              page.locator(".dish").count() > 0,
              str(page.locator(".dish").count()))
        page.locator(".dish").first.click()
        page.wait_for_timeout(400)
        disabled = page.get_by_role("button", name="Выберите вариант")
        check("без обязательного варианта добавить нельзя", disabled.count() > 0)
        # Выбор берётся по группам, а не по подписи: «50 мл» есть и внутри
        # «150 мл», и тест не должен угадывать.
        # Вид больше не выбирают: Absolut и Stoli стали разными позициями
        # меню — на полке это и есть разные бутылки.
        groups = page.locator(".sheet .group")
        groups.nth(0).locator(".opt").first.click()   # объём — 50 мл
        check("микс называет конкретный напиток",
              "Cola" in groups.nth(1).inner_text(),
              groups.nth(1).inner_text()[:90])
        page.wait_for_timeout(300)
        add = page.locator(".sheet .btn.primary")
        # Цена варианта тоже приезжает с сайта — сверяем с тем, что показано,
        # а не с цифрой, вписанной сюда однажды.
        poured = page.evaluate("""() => {
            const i = (App.menu.items || []).find(
                x => x.state === 'on' && (x.options || []).length);
            return i ? i.price_pence : null;
        }""")
        check("цена варианта показана до отправки", "£" in add.inner_text(), add.inner_text())
        add.click()
        page.wait_for_timeout(700)

        page.get_by_role("button", name="К чеку").click()
        page.wait_for_timeout(600)
        check("в чеке две позиции", page.locator(".line").count() == 2,
              str(page.locator(".line").count()))
        # Итог сверяем с ценами позиций, а не с цифрой, вписанной сюда
        # однажды: цены приезжают с сайта и меняются без спроса.
        want = money(simple["price"] + poured)
        check("итог посчитан", want in page.locator(".totals").inner_text(),
              f"ждали {want}, видно: " + page.locator(".totals").inner_text())
        check("черновик помечен", page.locator(".line.draft").count() == 2)

        # «И мне такое же»: в меню видно, сколько уже набрано, и есть «ещё
        # одну» — без прохода по вариантам заново. Рядом минус: гость
        # передумал так же часто, как попросил ещё.
        page.get_by_role("button", name="Меню").click()
        page.wait_for_timeout(700)
        page.locator(".search input").fill("")
        page.wait_for_timeout(400)
        picked = page.locator(".dish.picked").first
        check("в меню видно, сколько уже в чеке",
              "1×" in picked.locator(".in-check").inner_text(),
              picked.inner_text()[:60])
        picked.locator(".plus", has_text="+").click()
        page.wait_for_timeout(900)
        check("«ещё одну» прибавила к той же строке",
              "2×" in page.locator(".dish.picked").first.locator(".in-check").inner_text(),
              page.locator(".dish.picked").first.inner_text()[:60])

        page.get_by_role("button", name="К чеку").click()
        page.wait_for_timeout(700)
        check("строк в чеке не прибавилось", page.locator(".line").count() == 2,
              str(page.locator(".line").count()))
        check("а количество выросло",
              page.locator(".line", has_text="2×").count() >= 1,
              page.locator(".lines").inner_text()[:120])

        # Шторка строки закрывается нажатием мимо кнопок: фона над ней —
        # полоска, и раньше до неё приходилось прокручивать список обратно.
        page.locator(".line").first.click()
        page.wait_for_timeout(600)
        check("шторка строки открылась", page.locator("#sheet").count() == 1)
        head = page.locator("#sheet h2")
        box = head.bounding_box()
        page.mouse.move(box["x"] + 20, box["y"] + 5)
        page.mouse.down()
        page.mouse.move(box["x"] + 20, box["y"] - 60, steps=8)
        page.mouse.up()
        page.wait_for_timeout(500)
        check("протяжка по шторке её не закрывает", page.locator("#sheet").count() == 1)
        head.click()
        page.wait_for_timeout(500)
        check("нажатие мимо кнопок закрывает", page.locator("#sheet").count() == 0)

        # Передумали — минус там же, в меню. Уходить ради этого в чек значит
        # три нажатия там, где нужно одно.
        page.get_by_role("button", name="Меню").click()
        page.wait_for_timeout(700)
        page.locator(".dish.picked").first.locator(".plus", has_text="−").click()
        page.wait_for_timeout(900)
        check("минус убавил обратно",
              "1×" in page.locator(".dish.picked").first.locator(".in-check").inner_text(),
              page.locator(".dish.picked").first.inner_text()[:60])
        page.get_by_role("button", name="К чеку").click()
        page.wait_for_timeout(700)
        check("в чеке снова по одной",
              page.locator(".line", has_text="2×").count() == 0,
              page.locator(".lines").inner_text()[:120])

        # Стол открыли по ошибке — официант закрывает его сам, без менеджера.
        # Проверяем на втором чеке этого же стола: он пустой.
        # Компания за столом делится — второй чек нужен прямо отсюда.
        page.get_by_role("button", name="+ ещё чек").click()
        page.wait_for_timeout(500)
        check("второй чек на столе спрашивают", page.locator(".sheet").is_visible())
        page.get_by_role("button", name="Открыть стол").click()
        page.wait_for_timeout(900)
        # Новый чек открывается сразу на меню — набирать начинают тут же.
        page.get_by_role("button", name="К чеку").click()
        page.wait_for_timeout(600)
        check("второй чек открылся пустым", page.locator(".line").count() == 0,
              str(page.locator(".line").count()))
        # Брать нечего — и кнопка называет то, что случится.
        check("у пустого чека есть чем закрыть стол",
              page.get_by_role("button", name="Закрыть стол").count() == 1,
              " | ".join(b.inner_text() for b in page.locator(".dock button").all()))
        page.get_by_role("button", name="←").click()
        page.wait_for_timeout(700)
        busy = page.locator(f":is(.spot, .tile):has(:is(.n, .num):text-is('{label}'))")
        busy.click()
        page.wait_for_timeout(600)
        check("стол с двумя чеками спрашивает, какой открыть",
              page.locator(".sheet .btn").count() >= 3,
              str(page.locator(".sheet .btn").count()))
        page.locator(".sheet .btn").first.click()
        page.wait_for_timeout(800)
        check("вернулись в первый чек", page.locator(".line").count() == 2,
              str(page.locator(".line").count()))

        page.get_by_role("button", name="Отправить").click()
        page.wait_for_timeout(900)
        check("после отправки черновиков нет", page.locator(".line.draft").count() == 0)
        check("появилась кнопка оплаты", page.get_by_role("button", name="Оплата").count() > 0)

        page.get_by_role("button", name="Оплата").click()
        page.wait_for_timeout(400)
        page.get_by_role("button", name=f"Наличные · {want}").click()
        page.wait_for_timeout(400)
        # Дают на четыре фунта больше — столько и должно вернуться сдачей.
        page.locator(".sheet .field").fill(f"{(simple['price'] + poured) / 100 + 4:.2f}")
        page.wait_for_timeout(300)
        check("сдача посчитана", "£4.00" in page.locator(".sheet").inner_text(),
              page.locator(".sheet").inner_text()[:200])
        page.get_by_role("button", name=f"Принял {want}").click()
        page.wait_for_timeout(1200)

        check("вернулись к столам", page.locator(HALL).count() > 0)
        # На столе оставался второй чек — значит, закрылся ровно один, а стол
        # остаётся занятым. Пустая сумма показывает, что закрылся именно
        # первый, с позициями.
        tile = page.locator(f":is(.spot, .tile):has(:is(.n, .num):text-is('{label}'))")
        check("закрылся ровно один чек, стол остался с пустым вторым",
              "busy" in (tile.get_attribute("class") or "")
              and "£0.00" in tile.inner_text(),
              tile.inner_text().replace("\n", " "))

        tile.click()
        page.wait_for_timeout(700)
        check("оставшийся чек открывается без вопроса", page.locator(".sheet").count() == 0)
        page.get_by_role("button", name="Оплата").count()  # его нечем закрывать: он пуст

        # Приложение с домашнего экрана не перезагрузишь браузером: без этой
        # кнопки поправка доезжает, только когда официант переставит значок.
        page.get_by_role("button", name="←").click()
        page.wait_for_timeout(700)
        check("в зале есть чем обновиться",
              page.get_by_role("button", name="Обновить", exact=True).count() == 1)
        page.get_by_role("button", name="Обновить", exact=True).click()
        page.wait_for_timeout(2500)
        check("после обновления зал на месте и вход не спрашивают",
              page.locator(":is(.spot, .tile)").count() > 0
              and page.locator("#gate").count() == 0,
              page.url)

        # В полный зал ищут не по каталогу, а по памяти: половина заказов —
        # одни и те же позиции, и листать до них весь список неоткуда.
        page.locator(f":is(.spot, .tile):has(:is(.n, .num):text-is('{label}'))").first.click()
        page.wait_for_timeout(700)
        if page.locator(".sheet").count():
            page.locator(".sheet .btn").first.click()
            page.wait_for_timeout(700)
        if page.get_by_role("button", name="Меню").count():
            page.get_by_role("button", name="Меню").click()
            page.wait_for_timeout(700)
        check("часто берут — наверху меню",
              page.locator(".zone-title", has_text="Часто берут").count() == 1,
              page.locator(".screen").inner_text()[:120])

        check("ошибок в консоли нет", not errors, "; ".join(errors[:3]))
        browser.close()

    print()
    if fails:
        print("не прошло:", ", ".join(fails))
        sys.exit(1)
    print("зал работает")


if __name__ == "__main__":
    main()
