"""Смена планшета станции: свой PIN на открытие и на закрытие."""

from tests.test_floor import add, hall, login, open_check  # noqa: F401


def set_pin(client, station, pin):
    return client.post("/api/admin/stations/pin", json={"station": station, "pin": pin})


def test_station_pin_is_set_by_admins_only(client, hall):
    login(client, "1111")
    assert set_pin(client, "bar", "5555").status_code == 403
    login(client, "444444")   # менеджер
    assert set_pin(client, "bar", "5555").status_code == 403
    login(client, "123456")   # владелец
    assert set_pin(client, "bar", "5555").status_code == 200


def test_tablet_without_a_shift_sees_nothing(client, hall):
    """Планшет до открытия смены показывает экран PIN, а не пустую очередь."""
    login(client, "123456")
    set_pin(client, "bar", "5555")
    client.post("/api/auth/logout")

    state = client.get("/api/station/shift").json()
    assert state["open"] is False
    assert state["configured"] is True
    assert client.get("/api/station/queue").status_code == 401


def test_pin_alone_opens_the_right_station(client, hall):
    """Станцию не спрашивают: планшеты отличаются как раз PIN-ом."""
    login(client, "123456")
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
    login(client, "123456")
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

    login(client, "123456")
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

    login(client, "123456")
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

    login(client, "123456")
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
    login(client, "123456")
    set_pin(client, "bar", "5555")
    client.post("/api/auth/logout")

    first = client.post("/api/station/shift/open", json={"pin": "5555"}).json()
    second = client.post("/api/station/shift/open", json={"pin": "5555"}).json()
    assert first["opened_at"] == second["opened_at"]

    login(client, "123456")
    assert len(client.get("/api/admin/shifts").json()) == 1


def test_shift_log_shows_what_happened(client, hall):
    login(client, "123456")
    set_pin(client, "bar", "5555")
    client.post("/api/auth/logout")
    client.post("/api/station/shift/open", json={"pin": "5555"})
    client.post("/api/station/shift/close", json={"pin": "5555"})

    login(client, "123456")
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


# --------------------------------------------------- смена именем человека ---
def test_personal_pin_opens_the_shift_of_his_station(client, hall):
    """Бармен открывает смену своим PIN — и в смене остаётся его имя.

    Планшет один, а барменов за вечер бывает двое. «Смену открыл планшет» —
    ответ, который в спорный вечер не стоит ничего.
    """
    opened = client.post("/api/station/shift/open", json={"pin": "2222"})
    assert opened.status_code == 200
    body = opened.json()
    assert body["station"] == "bar"
    assert body["opened_by"] == "Игорь"

    # Планшет заработал и без общего PIN станции: его могли не задать вовсе.
    assert client.get("/api/station/queue").json()["station"] == "bar"


def test_kitchen_pin_opens_the_kitchen(client, hall):
    body = client.post("/api/station/shift/open", json={"pin": "3333"}).json()
    assert body["station"] == "kitchen"
    assert body["opened_by"] == "Пётр"


def test_waiter_pin_opens_no_station(client, hall):
    """Роль — это и есть допуск. Официанту станция не принадлежит."""
    assert client.post("/api/station/shift/open", json={"pin": "1111"}).status_code == 401


def test_disabled_bartender_no_longer_opens_shifts(client, hall, db):
    from app.models import User

    igor = db.query(User).filter(User.name == "Игорь").one()
    igor.active = False
    db.commit()
    assert client.post("/api/station/shift/open", json={"pin": "2222"}).status_code == 401


def test_shift_remembers_both_who_opened_and_who_closed(client, hall, db, make_user):
    """Смену сдают: закрыть может второй бармен, и в журнале будут оба."""
    make_user("Слава", role="bar", pin="2727")

    client.post("/api/station/shift/open", json={"pin": "2222"})
    closed = client.post("/api/station/shift/close", json={"pin": "2727"}).json()
    assert closed["opened_by"] == "Игорь"
    assert closed["closed_by"] == "Слава"

    login(client, "123456")
    row = client.get("/api/admin/shifts").json()[0]
    assert row["opened_by"] == "Игорь"
    assert row["closed_by"] == "Слава"


def test_kitchen_pin_does_not_close_the_bar(client, hall):
    client.post("/api/station/shift/open", json={"pin": "2222"})
    assert client.post("/api/station/shift/close", json={"pin": "3333"}).status_code == 401


def test_station_pin_stays_as_a_spare_key(client, hall):
    """Свой PIN забыли — общий PIN станции по-прежнему открывает смену.

    Только имени за такой сменой нет, и в журнале это видно.
    """
    login(client, "123456")
    set_pin(client, "bar", "5555")
    client.post("/api/auth/logout")

    body = client.post("/api/station/shift/open", json={"pin": "5555"}).json()
    assert body["station"] == "bar"
    assert body["opened_by"] is None


def test_personal_pin_wins_over_the_station_pin(client, hall, db):
    """Если владелец задал станции те же цифры, имя важнее.

    Иначе смена бармена навсегда осталась бы безымянной.
    """
    from app.services.auth import issue_pin
    from app.models import User

    igor = db.query(User).filter(User.name == "Игорь").one()
    issue_pin(db, igor, "7777")
    db.commit()

    login(client, "123456")
    set_pin(client, "bar", "7777")
    client.post("/api/auth/logout")

    assert client.post("/api/station/shift/open", json={"pin": "7777"}).json()["opened_by"] == "Игорь"


# ------------------------------------------------- двое на одной станции ---
def test_second_bartender_joins_the_open_shift(client, hall, make_user):
    """На баре двое — смена одна.

    Вторая смена на ту же станцию разрезала бы очередь марок пополам, поэтому
    второй не открывает свою, а встаёт в открытую.
    """
    make_user("Слава", role="bar", pin="2727")
    client.post("/api/station/shift/open", json={"pin": "2222"})

    joined = client.post("/api/station/shift/join", json={"pin": "2727"})
    assert joined.status_code == 200
    body = joined.json()
    assert body["joined"] == "Слава"
    assert body["people"] == ["Игорь", "Слава"]
    # Смена та же: очередь марок общая, планшет не перелогинивался.
    assert body["opened_by"] == "Игорь"
    assert body["open"] is True


def test_joining_twice_does_not_double_the_name(client, hall):
    """Отошёл и вернулся — та же строка, а не второй «Игорь» в списке."""
    client.post("/api/station/shift/open", json={"pin": "2222"})
    client.post("/api/station/shift/join", json={"pin": "2222"})
    assert client.get("/api/station/shift").json()["people"] == ["Игорь"]


def test_kitchen_cannot_join_the_bar(client, hall):
    client.post("/api/station/shift/open", json={"pin": "2222"})
    assert client.post("/api/station/shift/join", json={"pin": "3333"}).status_code == 401


def test_station_pin_adds_nobody(client, hall):
    """За общим PIN нет имени, а список без имён ни на что не отвечает."""
    login(client, "123456")
    set_pin(client, "bar", "5555")
    client.post("/api/auth/logout")

    client.post("/api/station/shift/open", json={"pin": "5555"})
    assert client.post("/api/station/shift/join", json={"pin": "5555"}).status_code == 401
    assert client.get("/api/station/shift").json()["people"] == []


def test_joining_without_an_open_shift_is_refused(client, hall):
    assert client.post("/api/station/shift/join", json={"pin": "2222"}).status_code == 409


def test_shift_log_lists_everyone_who_stood_there(client, hall, make_user):
    make_user("Слава", role="bar", pin="2727")
    client.post("/api/station/shift/open", json={"pin": "2222"})
    client.post("/api/station/shift/join", json={"pin": "2727"})
    client.post("/api/station/shift/close", json={"pin": "2727"})

    login(client, "123456")
    row = client.get("/api/admin/shifts").json()[0]
    assert row["people"] == ["Игорь", "Слава"]
    assert row["opened_by"] == "Игорь"
    assert row["closed_by"] == "Слава"

    journal = client.get("/api/admin/audit").json()
    assert any(r["action"] == "shift.join" for r in journal)


def test_the_one_who_closes_is_counted_as_present(client, hall, make_user):
    """Закрыл смену — значит, был на баре. Иначе список врёт."""
    make_user("Слава", role="bar", pin="2727")
    client.post("/api/station/shift/open", json={"pin": "2222"})
    closed = client.post("/api/station/shift/close", json={"pin": "2727"}).json()
    assert closed["people"] == ["Игорь", "Слава"]


def test_reopening_the_tablet_adds_whoever_unlocked_it(client, hall, make_user):
    """Планшет перезагрузили — смена та же, но второе имя в ней появится."""
    make_user("Слава", role="bar", pin="2727")
    first = client.post("/api/station/shift/open", json={"pin": "2222"}).json()
    again = client.post("/api/station/shift/open", json={"pin": "2727"}).json()
    assert again["opened_at"] == first["opened_at"]   # смена не переоткрылась
    assert again["opened_by"] == "Игорь"              # открыл всё равно первый
    assert again["people"] == ["Игорь", "Слава"]
