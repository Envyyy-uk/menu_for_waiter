"""Путь заказа целиком: открыл стол → набрал → отправил → бар отдал → закрыл."""

import pytest
from sqlalchemy import select, update

from app.models import MenuItem, Table


def login(client, pin):
    r = client.post("/api/auth/pin", json={"pin": pin})
    assert r.status_code == 200, r.text
    return r.json()


def table_id(db, venue, label="1"):
    return str(
        db.scalars(select(Table).where(Table.venue_id == venue.id, Table.label == label)).one().id
    )


def menu_id(db, key):
    return str(db.scalars(select(MenuItem).where(MenuItem.key == key)).one().id)


@pytest.fixture()
def hall(client, db, venue, make_user):
    """Официант, бармен и повар — по одному, как в маленькой смене.

    Меню при этом всё в продаже. В снимке каталога кухня помечена «скоро» —
    так она выключена на сайте прямо сейчас, — но проверять зал на выключенной
    кухне бессмысленно: стоп-лист с сайта разбирается своими тестами.
    """
    db.execute(update(MenuItem).values(state="on", source_state="on"))
    db.commit()
    make_user("Аня", role="waiter", pin="1111")
    make_user("Игорь", role="bar", pin="2222")
    make_user("Пётр", role="kitchen", pin="3333")
    make_user("Марина", role="manager", pin="444444")
    return {
        "table": table_id(db, venue),
        "mojito": menu_id(db, "mojito"),
        "pizza": menu_id(db, "pizza-margherita"),
    }


def open_check(client, hall, guests=2):
    r = client.post("/api/checks", json={"table_id": hall["table"], "guests": guests})
    assert r.status_code == 201, r.text
    return r.json()


def add(client, check_id, item_id, qty=1, options=None):
    return client.post(
        f"/api/checks/{check_id}/items",
        json={"menu_item_id": item_id, "qty": qty, "options": options or {}},
    )


# ------------------------------------------------------------------------
def test_open_check_shows_on_the_table(client, hall):
    login(client, "1111")
    check = open_check(client, hall)
    assert check["status"] == "open"
    assert check["guests"] == 2
    assert check["total_pence"] == 0

    tables = client.get("/api/tables").json()
    mine = next(t for t in tables if t["id"] == hall["table"])
    assert len(mine["checks"]) == 1
    assert mine["checks"][0]["mine"] is True


def test_server_counts_the_price(client, hall):
    login(client, "1111")
    check = open_check(client, hall)
    r = add(client, check["id"], hall["mojito"], qty=2)
    assert r.status_code == 201, r.text
    body = r.json()
    # Мохито £16.00 × 2. Браузер прислал только «что», не «почём».
    assert body["items"][0]["unit_price_pence"] == 1600
    assert body["total_pence"] == 3200


def test_draft_is_invisible_to_the_station(client, hall):
    """Пока официант не нажал «Отправить», на баре ничего нет."""
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])

    login(client, "2222")
    assert client.get("/api/station/queue").json()["tickets"] == []


def test_send_splits_by_station(client, hall):
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    add(client, check["id"], hall["pizza"])

    sent = client.post(f"/api/checks/{check['id']}/send").json()
    assert sent["has_draft"] is False
    assert len(sent["orders"]) == 1
    assert {t["station"] for t in sent["orders"][0]["tickets"]} == {"bar", "kitchen"}

    login(client, "2222")
    bar = client.get("/api/station/queue").json()
    assert bar["station_name"] == "Бар"
    assert len(bar["tickets"]) == 1
    assert [i["name"] for i in bar["tickets"][0]["items"]] == ["Mojito"]

    login(client, "3333")
    kitchen = client.get("/api/station/queue").json()
    assert [i["name"] for i in kitchen["tickets"][0]["items"]] == ["Margherita Pizza"]


def test_bar_ready_does_not_touch_the_kitchen(client, hall):
    """«Готово» в баре не делает готовым то, что кухня ещё жарит."""
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    add(client, check["id"], hall["pizza"])
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "2222")
    ticket = client.get("/api/station/queue").json()["tickets"][0]
    assert client.post(f"/api/station/tickets/{ticket['id']}/accepted").status_code == 200
    assert client.post(f"/api/station/tickets/{ticket['id']}/ready").status_code == 200

    login(client, "1111")
    state = client.get(f"/api/checks/{check['id']}").json()["stations"]
    assert state == {"bar": "ready", "kitchen": "new"}


def test_bar_cannot_touch_kitchen_ticket(client, hall):
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["pizza"])
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "3333")
    ticket = client.get("/api/station/queue").json()["tickets"][0]

    login(client, "2222")
    assert client.post(f"/api/station/tickets/{ticket['id']}/accepted").status_code == 403


def test_repeated_tap_does_not_break_anything(client, hall):
    """Мокрый палец на планшете жмёт дважды. Это не должно ничего ломать."""
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "2222")
    ticket = client.get("/api/station/queue").json()["tickets"][0]
    client.post(f"/api/station/tickets/{ticket['id']}/accepted")
    again = client.post(f"/api/station/tickets/{ticket['id']}/accepted")
    assert again.status_code == 200
    assert again.json()["status"] == "accepted"


def test_ready_cannot_go_back(client, hall):
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "2222")
    ticket = client.get("/api/station/queue").json()["tickets"][0]
    client.post(f"/api/station/tickets/{ticket['id']}/ready")
    assert client.post(f"/api/station/tickets/{ticket['id']}/accepted").status_code == 409


def test_waiter_sees_what_is_waiting_and_takes_it(client, hall):
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "2222")
    ticket = client.get("/api/station/queue").json()["tickets"][0]
    client.post(f"/api/station/tickets/{ticket['id']}/ready")

    login(client, "1111")
    waiting = client.get("/api/station/waiting").json()
    assert len(waiting) == 1
    assert waiting[0]["table"] == "1"

    assert client.post(f"/api/station/tickets/{ticket['id']}/served").status_code == 200
    assert client.get("/api/station/waiting").json() == []
    # Отданное уходит с планшета: это уже не работа.
    login(client, "2222")
    assert client.get("/api/station/queue").json()["tickets"] == []


def test_each_table_opens_its_own_check(client, db, venue, hall):
    """Два занятых стола — и каждый открывает свой чек.

    Ошибиться здесь означает принести заказ не туда и закрыть чужой чек.
    """
    login(client, "1111")
    first = open_check(client, hall)
    add(client, first["id"], hall["mojito"])

    second_table = table_id(db, venue, "2")
    second = client.post(
        "/api/checks", json={"table_id": second_table, "guests": 4}
    ).json()
    add(client, second["id"], hall["pizza"])

    assert first["id"] != second["id"]
    assert first["number"] != second["number"]

    tables = {t["id"]: t for t in client.get("/api/tables").json()}
    assert [c["id"] for c in tables[hall["table"]]["checks"]] == [first["id"]]
    assert [c["id"] for c in tables[second_table]["checks"]] == [second["id"]]

    # И суммы не перепутаны: у каждого стола своя.
    assert tables[hall["table"]]["checks"][0]["total_pence"] == 1600
    assert tables[second_table]["checks"][0]["total_pence"] == 1300

    one = client.get(f"/api/checks/{first['id']}").json()
    two = client.get(f"/api/checks/{second['id']}").json()
    assert [i["name"] for i in one["items"]] == ["Mojito"]
    assert [i["name"] for i in two["items"]] == ["Margherita Pizza"]


def test_one_table_can_hold_two_checks(client, hall):
    """Компания разделилась — и угадывать за официанта, какой чек он
    открывает, нельзя."""
    login(client, "1111")
    first = open_check(client, hall)
    second = open_check(client, hall, guests=3)
    assert first["id"] != second["id"]

    tables = {t["id"]: t for t in client.get("/api/tables").json()}
    numbers = sorted(c["number"] for c in tables[hall["table"]]["checks"])
    assert numbers == sorted([first["number"], second["number"]])


# ------------------------------------------------- «и мне такое же» --------
def test_the_same_thing_again_is_a_plus_one(client, hall):
    """Гость говорит «и мне такое же» — в чеке «2× Cola», а не две строки.

    Два одинаковых огрызка подряд читаются хуже, чем один с количеством, и
    считать их гостю приходится глазами.
    """
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    body = add(client, check["id"], hall["mojito"]).json()

    drafts = [i for i in body["items"] if i["status"] == "draft"]
    assert len(drafts) == 1
    assert drafts[0]["qty"] == 2


def test_a_comment_keeps_the_lines_apart(client, hall):
    """«Без льда» и обычный — разные напитки: бармен должен увидеть их порознь."""
    login(client, "1111")
    check = open_check(client, hall)
    client.post(f"/api/checks/{check['id']}/items",
                json={"menu_item_id": hall["mojito"], "qty": 1})
    body = client.post(f"/api/checks/{check['id']}/items",
                       json={"menu_item_id": hall["mojito"], "qty": 1,
                             "note": "без льда"}).json()

    drafts = [i for i in body["items"] if i["status"] == "draft"]
    assert len(drafts) == 2
    assert {i["note"] for i in drafts} == {None, "без льда"}


def test_what_was_sent_becomes_a_new_line(client, hall):
    """Отправленное уже налили. Заказали снова — это новая строка внизу.

    Дописать количество в отправленную значит соврать бару: там эта марка
    уже висит с прежней цифрой.
    """
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    client.post(f"/api/checks/{check['id']}/send")

    body = add(client, check["id"], hall["mojito"]).json()
    live = [i for i in body["items"] if i["status"] != "cancelled"]
    assert len(live) == 2
    assert sorted(i["qty"] for i in live) == [1, 1]


def test_the_last_one_taken_back_removes_the_line(client, hall):
    """Передумали до отправки — строка уходит целиком.

    «Минус» на последней порции значит «не будем», а не «оставьте ноль штук»:
    строка с нулём в чеке — это мусор, который потом читают глазами.
    """
    login(client, "1111")
    check = open_check(client, hall)
    body = add(client, check["id"], hall["mojito"]).json()
    line = next(i for i in body["items"] if i["status"] == "draft")

    after = client.patch(
        f"/api/checks/{check['id']}/items/{line['id']}", json={"qty": 0}).json()
    assert after["items"] == []
    assert after["total_pence"] == 0


def test_a_table_opened_by_mistake_closes_without_payment(client, hall):
    """Стол открыли и ничего не заказали — официант закрывает его сам.

    Брать за это нечего, а стол должен освободиться. Пока кнопки не было, он
    висел занятым до утра, и официант шёл за менеджером ради нуля.
    """
    login(client, "1111")
    check = open_check(client, hall)
    mine = lambda: next(t for t in client.get("/api/tables").json()
                        if t["id"] == check["table_id"])
    assert mine()["checks"]

    done = client.post(f"/api/checks/{check['id']}/close", json={"payments": []})
    assert done.status_code == 200
    assert done.json()["status"] == "closed"

    # Стол снова свободен.
    assert not mine()["checks"]


def test_a_table_with_an_unpaid_order_does_not_close_for_free(client, hall):
    """А чек с позициями закрывается только оплатой: иначе выручка теряется."""
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    client.post(f"/api/checks/{check['id']}/send")

    refused = client.post(f"/api/checks/{check['id']}/close", json={"payments": []})
    assert refused.status_code in (409, 422)


# --------------------------------------------- привычки заведения ----------
def test_the_menu_names_what_is_taken_often(client, hall):
    """В полный зал ищут не по каталогу, а по памяти.

    Половина заказов — одни и те же десять позиций, и листать до них весь
    список неоткуда.
    """
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"], qty=5)
    add(client, check["id"], hall["pizza"])

    menu = client.get("/api/menu").json()
    assert menu["popular"][0] == hall["mojito"]
    assert hall["pizza"] in menu["popular"]


def test_cancelled_is_not_a_habit(client, hall):
    """Гость передумал — значит, это не то, что берут часто."""
    login(client, "1111")
    check = open_check(client, hall)
    body = add(client, check["id"], hall["mojito"], qty=9).json()
    line = next(i for i in body["items"] if i["status"] == "draft")
    client.post(f"/api/checks/{check['id']}/items/{line['id']}/cancel",
                json={"reason": "передумали"})
    add(client, check["id"], hall["pizza"])

    menu = client.get("/api/menu").json()
    assert menu["popular"] == [hall["pizza"]]


def test_the_usual_variant_is_offered(client, hall, db):
    """Объём и микс почти всегда одни и те же — предлагаем их одним нажатием."""
    from sqlalchemy import select

    from app.models import MenuItem

    absolut = str(db.scalars(select(MenuItem).where(MenuItem.key == "absolut")).one().id)
    login(client, "1111")
    check = open_check(client, hall)
    for _ in range(2):
        client.post(f"/api/checks/{check['id']}/items", json={
            "menu_item_id": absolut,
            "options": {"size": "ml50", "mixer": ["cola"]},
            "note": f"раз{_}",
        })
    client.post(f"/api/checks/{check['id']}/items", json={
        "menu_item_id": absolut, "options": {"size": "bottle"}})

    usual = client.get("/api/menu").json()["usual"]
    assert usual[absolut] == {"size": "ml50", "mixer": ["cola"]}


def test_one_order_is_not_a_habit_yet(client, hall, db):
    """Один раз — это не «как обычно», а случайность."""
    from sqlalchemy import select

    from app.models import MenuItem

    absolut = str(db.scalars(select(MenuItem).where(MenuItem.key == "absolut")).one().id)
    login(client, "1111")
    check = open_check(client, hall)
    client.post(f"/api/checks/{check['id']}/items", json={
        "menu_item_id": absolut, "options": {"size": "ml50"}})

    assert client.get("/api/menu").json()["usual"] == {}
