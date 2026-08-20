"""Путь заказа целиком: открыл стол → набрал → отправил → бар отдал → закрыл."""

import pytest
from sqlalchemy import select

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
    """Официант, бармен и повар — по одному, как в маленькой смене."""
    make_user("Аня", role="waiter", pin="1111")
    make_user("Игорь", role="bar", pin="2222")
    make_user("Пётр", role="kitchen", pin="3333")
    make_user("Марина", role="manager", pin="4444")
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
