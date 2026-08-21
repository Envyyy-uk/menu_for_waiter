"""Склад: остаток — это сумма движений, и списывается он сам."""

from sqlalchemy import select

from app.models import MenuItem
from tests.test_floor import add, hall, login, open_check  # noqa: F401


def menu_id(db, key):
    return str(db.scalars(select(MenuItem).where(MenuItem.key == key)).one().id)


def make(client, name, unit="ml", quantity=0, low=0):
    return client.post(
        "/api/stock",
        json={"name": name, "unit": unit, "quantity": quantity, "low_at": low},
    ).json()


def stock_of(client, name):
    return next(i for i in client.get("/api/stock").json()["items"] if i["name"] == name)


# ------------------------------------------------------------- доступ -----
def test_stock_is_closed_to_everyone_but_admins(client, hall):
    """Остаток на полке — это деньги."""
    for pin in ("1111", "2222", "444444"):     # официант, бармен, менеджер
        login(client, pin)
        assert client.get("/api/stock").status_code == 403
    login(client, "123456")                    # владелец
    assert client.get("/api/stock").status_code == 200


# --------------------------------------------------------- ручной учёт ----
def test_starting_amount_is_an_arrival_not_a_number(client, hall):
    """Иначе первая же сверка не сойдётся, и объяснить будет нечем."""
    login(client, "123456")
    made = make(client, "Absolut", quantity=1500)
    assert made["quantity"] == 1500

    moves = client.get(f"/api/stock/{made['id']}/moves").json()
    assert moves[0]["reason"] == "in"
    assert moves[0]["delta"] == 1500
    assert moves[0]["note"] == "стартовый остаток"


def test_write_off_goes_down_even_if_asked_positive(client, hall):
    """Списание — это минус, как бы его ни ввели."""
    login(client, "123456")
    made = make(client, "Absolut", quantity=1000)
    client.post(f"/api/stock/{made['id']}/move",
                json={"delta": 200, "reason": "off", "note": "разбили"})
    assert stock_of(client, "Absolut")["quantity"] == 800


def test_inventory_records_the_difference(client, hall):
    """Главный вопрос инвентаризации — сколько не сошлось."""
    login(client, "123456")
    made = make(client, "Absolut", quantity=1000)
    client.post(f"/api/stock/{made['id']}/move", json={"counted": 940, "reason": "count"})

    assert stock_of(client, "Absolut")["quantity"] == 940
    moves = client.get(f"/api/stock/{made['id']}/moves").json()
    assert moves[0]["reason"] == "count"
    assert moves[0]["delta"] == -60


def test_low_and_empty_are_different_news(client, hall):
    login(client, "123456")
    make(client, "Absolut", quantity=100, low=200)
    make(client, "Beluga", quantity=0, low=200)
    make(client, "Jameson", quantity=900, low=200)

    body = client.get("/api/stock").json()
    assert body["low"] == ["Absolut"]
    assert body["out"] == ["Beluga"]
    assert stock_of(client, "Jameson")["state"] == "ok"


# ------------------------------------------------------ списание с продаж --
def test_sending_an_order_takes_it_off_the_shelf(client, db, hall):
    """Позиция ушла на станцию — её уже наливают."""
    login(client, "123456")
    bottle = make(client, "Absolut", quantity=1500)
    client.post("/api/stock/recipes", json={
        "menu_item_id": menu_id(db, "absolut"),
        "stock_item_id": bottle["id"],
        "options": {"size": "ml50"},
        "per_unit": 50,
    })

    login(client, "1111")
    check = open_check(client, hall)
    client.post(f"/api/checks/{check['id']}/items", json={
        "menu_item_id": menu_id(db, "absolut"),
        "qty": 2,
        "options": {"size": "ml50"},
    })
    # Черновик склада не трогает: его ещё могут стереть.
    login(client, "123456")
    assert stock_of(client, "Absolut")["quantity"] == 1500

    login(client, "1111")
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "123456")
    assert stock_of(client, "Absolut")["quantity"] == 1400
    moves = client.get(f"/api/stock/{bottle['id']}/moves").json()
    assert moves[0]["reason"] == "sale"
    assert moves[0]["delta"] == -100
    # У продажи есть имя: её записывает тот, кто отправил заказ.
    assert moves[0]["who"] == "Аня"


def test_recipe_matches_the_chosen_variant(client, db, hall):
    """50 мл и бутылка — одна строка меню и совсем разный расход."""
    login(client, "123456")
    bottle = make(client, "Absolut", quantity=2000)
    for size, per in (("ml50", 50), ("bottle", 700)):
        client.post("/api/stock/recipes", json={
            "menu_item_id": menu_id(db, "absolut"),
            "stock_item_id": bottle["id"],
            "options": {"size": size},
            "per_unit": per,
        })

    login(client, "1111")
    check = open_check(client, hall)
    client.post(f"/api/checks/{check['id']}/items", json={
        "menu_item_id": menu_id(db, "absolut"),
        "options": {"size": "bottle"},
    })
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "123456")
    assert stock_of(client, "Absolut")["quantity"] == 1300


def test_cancelling_puts_it_back(client, db, hall):
    login(client, "123456")
    bottle = make(client, "Absolut", quantity=1000)
    client.post("/api/stock/recipes", json={
        "menu_item_id": menu_id(db, "absolut"),
        "stock_item_id": bottle["id"],
        "options": {"size": "ml50"},
        "per_unit": 50,
    })

    login(client, "1111")
    check = open_check(client, hall)
    check = client.post(f"/api/checks/{check['id']}/items", json={
        "menu_item_id": menu_id(db, "absolut"),
        "options": {"size": "ml50"},
    }).json()
    check = client.post(f"/api/checks/{check['id']}/send").json()
    item = check["items"][0]["id"]

    login(client, "123456")
    assert stock_of(client, "Absolut")["quantity"] == 950

    login(client, "444444")   # отменяет менеджер
    client.post(f"/api/checks/{check['id']}/items/{item}/cancel", json={"reason": "передумали"})

    login(client, "123456")
    assert stock_of(client, "Absolut")["quantity"] == 1000
    assert client.get(f"/api/stock/{bottle['id']}/moves").json()[0]["reason"] == "return"


def test_item_without_a_recipe_touches_nothing(client, db, hall):
    """Пока рецепта нет, склад просто не знает про эту позицию — и молчит."""
    login(client, "123456")
    make(client, "Absolut", quantity=1000)

    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "123456")
    assert stock_of(client, "Absolut")["quantity"] == 1000


def test_waiter_cannot_sell_more_than_there_is(client, db, hall):
    """Больше, чем стоит на полке, не набрать.

    Решение владельца: пусть лучше официант увидит отказ у стола, чем гость
    получит «извините, закончилось» после того, как заказ приняли.
    """
    login(client, "123456")
    bottle = make(client, "Absolut", quantity=30)
    client.post("/api/stock/recipes", json={
        "menu_item_id": menu_id(db, "absolut"),
        "stock_item_id": bottle["id"],
        "options": {"size": "ml50"},
        "per_unit": 50,
    })

    login(client, "1111")
    check = open_check(client, hall)
    r = client.post(f"/api/checks/{check['id']}/items", json={
        "menu_item_id": menu_id(db, "absolut"),
        "options": {"size": "ml50"},
    })
    assert r.status_code == 409
    # Сообщение называет и продукт, и цифры: официанту говорить это гостю.
    assert "Absolut" in r.json()["detail"]
    assert "50" in r.json()["detail"] and "30" in r.json()["detail"]

    # Позиция в чек не попала.
    assert client.get(f"/api/checks/{check['id']}").json()["items"] == []


def test_the_limit_counts_the_whole_check(client, db, hall):
    """Три раза по 50 мл — это те же 150, и упереться надо на третьем."""
    login(client, "123456")
    bottle = make(client, "Absolut", quantity=100)
    client.post("/api/stock/recipes", json={
        "menu_item_id": menu_id(db, "absolut"),
        "stock_item_id": bottle["id"],
        "options": {"size": "ml50"},
        "per_unit": 50,
    })

    login(client, "1111")
    check = open_check(client, hall)
    body = {"menu_item_id": menu_id(db, "absolut"),
            "options": {"size": "ml50"}}
    assert client.post(f"/api/checks/{check['id']}/items", json=body).status_code == 201
    assert client.post(f"/api/checks/{check['id']}/items", json=body).status_code == 201
    assert client.post(f"/api/checks/{check['id']}/items", json=body).status_code == 409


def test_a_position_without_a_recipe_is_not_limited(client, db, hall):
    """Склад знает не про всё, и останавливать зал из-за пробела в учёте нельзя."""
    login(client, "1111")
    check = open_check(client, hall)
    r = client.post(f"/api/checks/{check['id']}/items",
                    json={"menu_item_id": hall["mojito"], "qty": 99})
    assert r.status_code == 201


def test_write_off_can_take_it_below_zero(client, db, hall):
    """Минус в остатке значит, что с полки брали мимо учёта. Прятать это нельзя."""
    login(client, "123456")
    bottle = make(client, "Absolut", quantity=30)
    client.post(f"/api/stock/{bottle['id']}/move",
                json={"delta": 50, "reason": "off", "note": "разбили"})
    item = stock_of(client, "Absolut")
    assert item["quantity"] == -20
    assert item["state"] == "out"


def test_recipe_shows_the_variant_by_name(client, db, hall):
    """Правило списания читают глазами, сверяя с бутылкой на полке."""
    login(client, "123456")
    bottle = make(client, "Absolut", quantity=1000)
    client.post("/api/stock/recipes", json={
        "menu_item_id": menu_id(db, "absolut"),
        "stock_item_id": bottle["id"],
        "options": {"size": "ml50"},
        "per_unit": 50,
    })
    recipe = client.get("/api/stock/recipes").json()[0]
    assert recipe["options_text"] == "Объём: 50 мл"

    client.post("/api/stock/recipes", json={
        "menu_item_id": menu_id(db, "mojito"),
        "stock_item_id": bottle["id"],
        "per_unit": 40,
    })
    any_variant = next(r for r in client.get("/api/stock/recipes").json() if r["menu_item"] == "Mojito")
    assert any_variant["options_text"] == ""


def test_mixer_goes_off_the_shelf_too(client, db, hall):
    """Микс — тоже расход: банка колы уходит так же, как налитая водка.

    Выбранное в группе с несколькими выборами лежит списком, и «Cola» может
    стоять в нём дважды — гость взял водку с двумя колами. Значит, и банок
    уходит две.
    """
    login(client, "123456")
    cola = make(client, "Cola 0.33", unit="pc", quantity=10)
    client.post("/api/stock/recipes", json={
        "menu_item_id": menu_id(db, "absolut"),
        "stock_item_id": cola["id"],
        "options": {"mixer": "cola"},
        "per_unit": 1,
    })

    login(client, "1111")
    check = open_check(client, hall)
    client.post(f"/api/checks/{check['id']}/items", json={
        "menu_item_id": menu_id(db, "absolut"),
        "options": {"size": "ml50", "mixer": ["cola", "cola"]},
    })
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "123456")
    assert stock_of(client, "Cola 0.33")["quantity"] == 8


def test_mixer_of_another_kind_is_not_touched(client, db, hall):
    login(client, "123456")
    cola = make(client, "Cola 0.33", unit="pc", quantity=10)
    client.post("/api/stock/recipes", json={
        "menu_item_id": menu_id(db, "absolut"),
        "stock_item_id": cola["id"],
        "options": {"mixer": "cola"},
        "per_unit": 1,
    })

    login(client, "1111")
    check = open_check(client, hall)
    client.post(f"/api/checks/{check['id']}/items", json={
        "menu_item_id": menu_id(db, "absolut"),
        "options": {"size": "ml50", "mixer": ["sprite"]},
    })
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "123456")
    assert stock_of(client, "Cola 0.33")["quantity"] == 10


# ---------------------------------------- склад заводится по меню сам ------
def test_fill_makes_a_line_and_a_rule_for_every_position(client, db, hall):
    """Заполнять сорок позиций руками — вечер работы, и на середине бросают."""
    login(client, "123456")
    made = client.post("/api/stock/fill").json()
    assert made["items"] > 30
    assert made["recipes"] == made["items"]

    items = client.get("/api/stock").json()["items"]
    absolut = next(i for i in items if i["name"] == "Absolut")
    # У позиции с объёмами склад в миллилитрах, у остального — поштучно.
    assert absolut["unit"] == "ml"
    assert absolut["quantity"] == 0          # сколько на полке, знает человек
    pizza = next(i for i in items if "Margherita" in i["name"])
    assert pizza["unit"] == "pc"


def test_volume_rule_takes_what_the_waiter_chose(client, db, hall):
    """Одно правило вместо семи: выбрал 150 мл — ушло 150."""
    login(client, "123456")
    client.post("/api/stock/fill")
    absolut = next(i for i in client.get("/api/stock").json()["items"] if i["name"] == "Absolut")
    client.post(f"/api/stock/{absolut['id']}/move",
                json={"delta": 700, "reason": "in", "note": "привезли"})

    login(client, "1111")
    check = open_check(client, hall)
    client.post(f"/api/checks/{check['id']}/items",
                json={"menu_item_id": menu_id(db, "absolut"), "options": {"size": "ml150"}})
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "123456")
    assert stock_of(client, "Absolut")["quantity"] == 550


def test_a_bottle_takes_the_whole_bottle(client, db, hall):
    """У «бутылки» объёма в варианте нет — её размер записан в правиле."""
    login(client, "123456")
    client.post("/api/stock/fill")
    absolut = next(i for i in client.get("/api/stock").json()["items"] if i["name"] == "Absolut")
    client.post(f"/api/stock/{absolut['id']}/move",
                json={"delta": 1400, "reason": "in", "note": "две бутылки"})

    login(client, "1111")
    check = open_check(client, hall)
    client.post(f"/api/checks/{check['id']}/items",
                json={"menu_item_id": menu_id(db, "absolut"), "options": {"size": "bottle"}})
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "123456")
    assert stock_of(client, "Absolut")["quantity"] == 700


def test_fill_does_not_touch_what_was_set_by_hand(client, db, hall):
    """Правило, заведённое руками, важнее заготовки."""
    login(client, "123456")
    bottle = make(client, "Своя бутылка", quantity=500)
    client.post("/api/stock/recipes", json={
        "menu_item_id": menu_id(db, "absolut"),
        "stock_item_id": bottle["id"],
        "options": {"size": "ml50"},
        "per_unit": 50,
    })
    client.post("/api/stock/fill")

    rules = [r for r in client.get("/api/stock/recipes").json()
             if r["menu_item"] == "Absolut"]
    assert len(rules) == 1
    assert rules[0]["stock_item"] == "Своя бутылка"


# ------------------------------------------------- инвентаризация ---------
def test_inventory_sheet_shows_what_should_be_there(client, db, hall):
    """Лист на сегодня: расчётный остаток против полки."""
    login(client, "123456")
    make(client, "Absolut", quantity=700)
    body = client.get("/api/stock/inventory").json()
    line = next(r for r in body["sheet"] if r["name"] == "Absolut")
    assert line["expected"] == 700
    assert line["unit_name"] == "мл"


def test_inventory_keeps_the_difference_by_month(client, db, hall):
    """Через полгода вопрос звучит «когда расхождение началось»."""
    login(client, "123456")
    bottle = make(client, "Absolut", quantity=700)
    client.post(f"/api/stock/{bottle['id']}/move",
                json={"reason": "count", "counted": 650, "note": "инвентаризация"})

    body = client.get("/api/stock/inventory").json()
    assert len(body["months"]) == 1
    rows = body["history"]["rows"]
    assert len(rows) == 1
    # Записана разница, а не новое число: само число ничего не объясняет.
    assert rows[0]["difference"] == -50
    assert rows[0]["name"] == "Absolut"
    assert rows[0]["who"] == "Владелец"
    assert body["history"]["gap"] == -50

    # И остаток стал тем, что на полке.
    assert stock_of(client, "Absolut")["quantity"] == 650


def test_inventory_is_not_for_the_waiter(client, db, hall):
    login(client, "1111")
    assert client.get("/api/stock/inventory").status_code == 403
