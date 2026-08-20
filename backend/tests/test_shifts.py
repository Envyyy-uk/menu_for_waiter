"""Смена планшета станции: свой PIN на открытие и на закрытие."""

from tests.test_floor import add, hall, login, open_check  # noqa: F401


def set_pin(client, station, pin):
    return client.post("/api/admin/stations/pin", json={"station": station, "pin": pin})


def test_station_pin_is_set_by_admins_only(client, hall):
    login(client, "1111")
    assert set_pin(client, "bar", "5555").status_code == 403
    login(client, "4444")   # менеджер
    assert set_pin(client, "bar", "5555").status_code == 403
    login(client, "1234")   # владелец
    assert set_pin(client, "bar", "5555").status_code == 200


def test_tablet_without_a_shift_sees_nothing(client, hall):
    """Планшет до открытия смены показывает экран PIN, а не пустую очередь."""
    login(client, "1234")
    set_pin(client, "bar", "5555")
    client.post("/api/auth/logout")

    state = client.get("/api/station/shift").json()
    assert state["open"] is False
    assert state["configured"] is True
    assert client.get("/api/station/queue").status_code == 401


def test_pin_alone_opens_the_right_station(client, hall):
    """Станцию не спрашивают: планшеты отличаются как раз PIN-ом."""
    login(client, "1234")
    set_pin(client, "bar", "5555")
    set_pin(client, "kitchen", "6666")
    client.post("/api/auth/logout")

    opened = client.post("/api/station/shift/open", json={"pin": "6666"})
    assert opened.status_code == 200
    assert opened.json()["station"] == "kitchen"
    assert opened.json()["open"] is True

    queue = client.get("/api/station/queue").json()
    assert queue["station"] == "kitchen"
    assert queue["shift"]["open"] is True


def test_wrong_pin_does_not_open_anything(client, hall):
    login(client, "1234")
    set_pin(client, "bar", "5555")
    client.post("/api/auth/logout")
    assert client.post("/api/station/shift/open", json={"pin": "0000"}).status_code == 401
    assert client.get("/api/station/queue").status_code == 401


def test_tablet_works_without_a_personal_login(client, hall):
    """Планшет стоит на полке: личный PIN на каждую марку никто вводить не станет."""
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "1234")
    set_pin(client, "bar", "5555")
    client.post("/api/auth/logout")

    client.post("/api/station/shift/open", json={"pin": "5555"})
    queue = client.get("/api/station/queue").json()
    assert len(queue["tickets"]) == 1

    ticket = queue["tickets"][0]
    assert client.post(f"/api/station/tickets/{ticket['id']}/accepted").status_code == 200
    assert client.post(f"/api/station/tickets/{ticket['id']}/ready").status_code == 200

    # И официант получил свою марку как обычно.
    login(client, "1111")
    assert len(client.get("/api/station/waiting").json()) == 1


def test_tablet_cannot_touch_another_station(client, hall):
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["pizza"])       # кухня
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "3333")
    kitchen_ticket = client.get("/api/station/queue").json()["tickets"][0]

    login(client, "1234")
    set_pin(client, "bar", "5555")
    client.post("/api/auth/logout")
    client.post("/api/station/shift/open", json={"pin": "5555"})

    r = client.post(f"/api/station/tickets/{kitchen_ticket['id']}/ready")
    assert r.status_code == 403


def test_closing_needs_the_same_pin_and_counts_the_work(client, hall):
    """Иначе смену закрывает любой, кто прошёл мимо планшета."""
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "1234")
    set_pin(client, "bar", "5555")
    set_pin(client, "kitchen", "6666")
    client.post("/api/auth/logout")

    client.post("/api/station/shift/open", json={"pin": "5555"})
    ticket = client.get("/api/station/queue").json()["tickets"][0]
    client.post(f"/api/station/tickets/{ticket['id']}/ready")

    # Чужой PIN станции смену не закрывает.
    assert client.post("/api/station/shift/close", json={"pin": "6666"}).status_code == 401

    closed = client.post("/api/station/shift/close", json={"pin": "5555"}).json()
    assert closed["open"] is False
    assert closed["tickets_done"] == 1
    # После закрытия планшет снова просит PIN.
    assert client.get("/api/station/queue").status_code == 401


def test_reopening_keeps_the_same_shift(client, hall):
    """Планшет перезагрузили — смена та же, а не вторая за вечер."""
    login(client, "1234")
    set_pin(client, "bar", "5555")
    client.post("/api/auth/logout")

    first = client.post("/api/station/shift/open", json={"pin": "5555"}).json()
    second = client.post("/api/station/shift/open", json={"pin": "5555"}).json()
    assert first["opened_at"] == second["opened_at"]

    login(client, "1234")
    assert len(client.get("/api/admin/shifts").json()) == 1


def test_shift_log_shows_what_happened(client, hall):
    login(client, "1234")
    set_pin(client, "bar", "5555")
    client.post("/api/auth/logout")
    client.post("/api/station/shift/open", json={"pin": "5555"})
    client.post("/api/station/shift/close", json={"pin": "5555"})

    login(client, "1234")
    log = client.get("/api/admin/shifts").json()
    assert log[0]["name"] == "Бар"
    assert log[0]["closed_at"] is not None

    journal = client.get("/api/admin/audit").json()
    assert any(r["action"] == "shift.open" for r in journal)
    assert any(r["action"] == "shift.close" for r in journal)


def test_bartender_still_uses_his_own_login(client, hall):
    """Личный вход бармена никуда не делся: он пробивает и готовит сам."""
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "2222")
    queue = client.get("/api/station/queue").json()
    assert queue["station"] == "bar"
    assert queue["shift"] is None          # он не планшет, смены у него нет
    assert len(queue["tickets"]) == 1
