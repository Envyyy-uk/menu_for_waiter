"""Админка: персонал, столы, меню, отчёт."""

from tests.test_floor import add, hall, login, open_check  # noqa: F401


def test_staff_list_is_not_for_everyone(client, hall):
    """Официанту список не нужен, менеджеру — нужен ради забытого PIN,
    а заводить людей может только администратор."""
    login(client, "1111")
    assert client.get("/api/admin/users").status_code == 403

    login(client, "444444")  # менеджер: смотреть да, менять нет
    assert client.get("/api/admin/users").status_code == 200
    assert client.post(
        "/api/admin/users", json={"name": "Кто-то", "role": "waiter"}
    ).status_code == 403

    login(client, "123456")  # владелец из сидера
    assert client.get("/api/admin/users").status_code == 200


def test_new_employee_gets_a_pin_shown_once(client, hall):
    login(client, "123456")
    body = client.post(
        "/api/admin/users", json={"name": "Света", "role": "waiter", "pin": "5150"}
    ).json()
    assert body["pin"] == "5150"
    assert body["has_pin"] is True

    # И этим PIN она сразу входит — своей ролью, в своё приложение.
    me = client.post("/api/auth/pin", json={"pin": "5150"}).json()
    assert me["name"] == "Света"
    assert me["home"] == "/"


def test_pin_is_never_shown_again(client, hall):
    login(client, "123456")
    created = client.post("/api/admin/users", json={"name": "Света", "role": "waiter"}).json()
    assert len(created["pin"]) == 4

    listing = client.get("/api/admin/users").json()
    who = next(u for u in listing if u["name"] == "Света")
    # Подсмотреть PIN нельзя даже администратору: в базе только хеш.
    assert "pin" not in who
    assert who["has_pin"] is True


def test_nobody_hands_out_a_role_above_their_own(client, hall):
    login(client, "123456")
    # Владелец может завести второго владельца — заведение с одним владельцем
    # умирает вместе с его PIN.
    assert client.post(
        "/api/admin/users", json={"name": "Второй", "role": "owner", "pin": "991199"}
    ).status_code == 201


def test_admin_cannot_lock_himself_out(client, hall):
    login(client, "123456")
    me = client.get("/api/auth/me").json()
    r = client.patch(f"/api/admin/users/{me['id']}", json={"active": False})
    assert r.status_code == 409


def test_reset_pin_replaces_the_old_one(client, hall):
    login(client, "123456")
    users = client.get("/api/admin/users").json()
    anya = next(u for u in users if u["name"] == "Аня")
    client.post(f"/api/admin/users/{anya['id']}/pin", json={"pin": "7007"})

    assert client.post("/api/auth/pin", json={"pin": "7007"}).status_code == 200
    assert client.post("/api/auth/pin", json={"pin": "1111"}).status_code == 401


def test_table_with_an_open_check_cannot_be_switched_off(client, hall):
    """Иначе чек повиснет в никуда, и денег за него никто не возьмёт."""
    login(client, "1111")
    open_check(client, hall)

    login(client, "123456")
    r = client.patch(f"/api/admin/tables/{hall['table']}", json={"active": False})
    assert r.status_code == 409


def test_table_numbers_do_not_repeat(client, hall):
    login(client, "123456")
    assert client.post("/api/admin/tables", json={"label": "1"}).status_code == 409
    assert client.post("/api/admin/tables", json={"label": "101", "zone": "Терраса"}).status_code == 201


def test_price_change_is_written_down(client, hall):
    login(client, "123456")
    client.patch(f"/api/admin/menu/{hall['mojito']}", json={"price_pence": 1800})

    journal = client.get("/api/admin/audit").json()
    entry = next(r for r in journal if r["action"] == "item.edit")
    assert entry["before"]["price_pence"] == 1600
    assert entry["after"]["price_pence"] == 1800
    assert entry["who"] == "Владелец"


def test_shift_report_adds_up(client, hall):
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"], qty=2)        # £32.00
    client.post(f"/api/checks/{check['id']}/send")
    client.post(
        f"/api/checks/{check['id']}/close",
        json={
            "payments": [
                {"method": "card", "amount_pence": 2000},
                {"method": "cash", "amount_pence": 1200},
            ]
        },
    )

    login(client, "444444")  # отчёт смотрит менеджер
    r = client.get("/api/admin/report").json()
    assert r["checks"] == 1
    assert r["revenue_pence"] == 3200
    assert r["card_pence"] == 2000
    assert r["cash_pence"] == 1200
    assert r["average_pence"] == 3200
    assert r["by_waiter"][0]["name"] == "Аня"
    assert r["top_items"][0] == {"name": "Mojito", "qty": 2}


def test_report_shows_cancellations(client, hall):
    """То, ради чего отчёт открывают, когда сходится не всё."""
    login(client, "1111")
    check = open_check(client, hall)
    check = add(client, check["id"], hall["mojito"]).json()
    check = client.post(f"/api/checks/{check['id']}/send").json()
    item = check["items"][0]["id"]

    login(client, "444444")
    client.post(f"/api/checks/{check['id']}/items/{item}/cancel", json={"reason": "ушли"})
    r = client.get("/api/admin/report").json()
    assert r["cancelled"] == {"count": 1, "amount_pence": 1600}


def test_a_person_who_never_worked_can_be_removed(client, hall):
    """Заведённого по ошибке надо убирать: за год список зарастает опечатками."""
    login(client, "123456")
    made = client.post(
        "/api/admin/users", json={"name": "Опечатка", "role": "waiter", "pin": "5151"}
    ).json()
    assert client.delete(f"/api/admin/users/{made['id']}").status_code == 200
    assert all(u["name"] != "Опечатка" for u in client.get("/api/admin/users").json())


def test_a_person_who_worked_stays(client, hall):
    """Отчёт за прошлый месяц должен знать, чья это выручка."""
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "123456")
    anya = next(u for u in client.get("/api/admin/users").json() if u["name"] == "Аня")
    assert anya["worked"] is True
    r = client.delete(f"/api/admin/users/{anya['id']}")
    assert r.status_code == 409
    assert "выключить" in r.json()["detail"]
    # Выключить при этом можно.
    assert client.patch(
        f"/api/admin/users/{anya['id']}", json={"active": False}
    ).status_code == 200


def test_nobody_deletes_himself(client, hall):
    login(client, "123456")
    me = client.get("/api/auth/me").json()
    assert client.delete(f"/api/admin/users/{me['id']}").status_code == 409
