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
    for pin in ("1111", "2222", "4444"):     # официант, бармен, менеджер
        login(client, pin)
        assert client.get("/api/stock").status_code == 403
    login(client, "1234")                    # владелец
    assert client.get("/api/stock").status_code == 200


# --------------------------------------------------------- ручной учёт ----
def test_starting_amount_is_an_arrival_not_a_number(client, hall):
    """Иначе первая же сверка не сойдётся, и объяснить будет нечем."""
    login(client, "1234")
    made = make(client, "Absolut", quantity=1500)
    assert made["quantity"] == 1500

    moves = client.get(f"/api/stock/{made['id']}/moves").json()
    assert moves[0]["reason"] == "in"
    assert moves[0]["delta"] == 1500
    assert moves[0]["note"] == "стартовый остаток"


def test_write_off_goes_down_even_if_asked_positive(client, hall):
    """Списание — это минус, как бы его ни ввели."""
    login(client, "1234")
    made = make(client, "Absolut", quantity=1000)
    client.post(f"/api/stock/{made['id']}/move",
                json={"delta": 200, "reason": "off", "note": "разбили"})
    assert stock_of(client, "Absolut")["quantity"] == 800


def test_inventory_records_the_difference(client, hall):
    """Главный вопрос инвентаризации — сколько не сошлось."""
    login(client, "1234")
    made = make(client, "Absolut", quantity=1000)
    client.post(f"/api/stock/{made['id']}/move", json={"counted": 940, "reason": "count"})

    assert stock_of(client, "Absolut")["quantity"] == 940
    moves = client.get(f"/api/stock/{made['id']}/moves").json()
    assert moves[0]["reason"] == "count"
    assert moves[0]["delta"] == -60


def test_low_and_empty_are_different_news(client, hall):
    login(client, "1234")
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
    login(client, "1234")
    bottle = make(client, "Absolut", quantity=1500)
    client.post("/api/stock/recipes", json={
        "menu_item_id": menu_id(db, "vodka-house"),
        "stock_item_id": bottle["id"],
        "options": {"size": "ml50"},
        "per_unit": 50,
    })

    login(client, "1111")
    check = open_check(client, hall)
    client.post(f"/api/checks/{check['id']}/items", json={
        "menu_item_id": menu_id(db, "vodka-house"),
        "qty": 2,
        "options": {"size": "ml50", "kind": "absolut"},
    })
    # Черновик склада не трогает: его ещё могут стереть.
    login(client, "1234")
    assert stock_of(client, "Absolut")["quantity"] == 1500

    login(client, "1111")
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "1234")
    assert stock_of(client, "Absolut")["quantity"] == 1400
    moves = client.get(f"/api/stock/{bottle['id']}/moves").json()
    assert moves[0]["reason"] == "sale"
    assert moves[0]["delta"] == -100
    # У продажи есть имя: её записывает тот, кто отправил заказ.
    assert moves[0]["who"] == "Аня"


def test_recipe_matches_the_chosen_variant(client, db, hall):
    """50 мл и бутылка — одна строка меню и совсем разный расход."""
    login(client, "1234")
    bottle = make(client, "Absolut", quantity=2000)
    for size, per in (("ml50", 50), ("bottle", 700)):
        client.post("/api/stock/recipes", json={
            "menu_item_id": menu_id(db, "vodka-house"),
            "stock_item_id": bottle["id"],
            "options": {"size": size},
            "per_unit": per,
        })

    login(client, "1111")
    check = open_check(client, hall)
    client.post(f"/api/checks/{check['id']}/items", json={
        "menu_item_id": menu_id(db, "vodka-house"),
        "options": {"size": "bottle", "kind": "absolut"},
    })
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "1234")
    assert stock_of(client, "Absolut")["quantity"] == 1300


def test_cancelling_puts_it_back(client, db, hall):
    login(client, "1234")
    bottle = make(client, "Absolut", quantity=1000)
    client.post("/api/stock/recipes", json={
        "menu_item_id": menu_id(db, "vodka-house"),
        "stock_item_id": bottle["id"],
        "options": {"size": "ml50"},
        "per_unit": 50,
    })

    login(client, "1111")
    check = open_check(client, hall)
    check = client.post(f"/api/checks/{check['id']}/items", json={
        "menu_item_id": menu_id(db, "vodka-house"),
        "options": {"size": "ml50", "kind": "absolut"},
    }).json()
    check = client.post(f"/api/checks/{check['id']}/send").json()
    item = check["items"][0]["id"]

    login(client, "1234")
    assert stock_of(client, "Absolut")["quantity"] == 950

    login(client, "4444")   # отменяет менеджер
    client.post(f"/api/checks/{check['id']}/items/{item}/cancel", json={"reason": "передумали"})

    login(client, "1234")
    assert stock_of(client, "Absolut")["quantity"] == 1000
    assert client.get(f"/api/stock/{bottle['id']}/moves").json()[0]["reason"] == "return"


def test_item_without_a_recipe_touches_nothing(client, db, hall):
    """Пока рецепта нет, склад просто не знает про эту позицию — и молчит."""
    login(client, "1234")
    make(client, "Absolut", quantity=1000)

    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "1234")
    assert stock_of(client, "Absolut")["quantity"] == 1000


def test_stock_can_go_negative_and_says_so(client, db, hall):
    """Отрицательный остаток не запрещаем: он означает, что на полке брали
    то, чего по учёту нет, и прятать это нельзя."""
    login(client, "1234")
    bottle = make(client, "Absolut", quantity=30)
    client.post("/api/stock/recipes", json={
        "menu_item_id": menu_id(db, "vodka-house"),
        "stock_item_id": bottle["id"],
        "options": {"size": "ml50"},
        "per_unit": 50,
    })

    login(client, "1111")
    check = open_check(client, hall)
    client.post(f"/api/checks/{check['id']}/items", json={
        "menu_item_id": menu_id(db, "vodka-house"),
        "options": {"size": "ml50", "kind": "absolut"},
    })
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "1234")
    item = stock_of(client, "Absolut")
    assert item["quantity"] == -20
    assert item["state"] == "out"


def test_recipe_shows_the_variant_by_name(client, db, hall):
    """Правило списания читают глазами, сверяя с бутылкой на полке."""
    login(client, "1234")
    bottle = make(client, "Absolut", quantity=1000)
    client.post("/api/stock/recipes", json={
        "menu_item_id": menu_id(db, "vodka-house"),
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
