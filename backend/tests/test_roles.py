"""Роли и пароли: кто кого может трогать."""

from tests.test_floor import hall, login  # noqa: F401


def me(client):
    return client.get("/api/auth/me").json()


def users(client):
    return client.get("/api/admin/users").json()


def test_first_login_is_the_owner(client, hall):
    """Заведение заводит тот, кому оно принадлежит."""
    body = login(client, "123456")
    assert body["role"] == "owner"
    assert body["role_name"] == "Владелец"
    assert "venue.manage" in body["permissions"]


def test_bartender_works_the_floor_and_the_station(client, hall):
    """За стойкой сидят гости, и заказ у них принимает бармен."""
    body = login(client, "2222")
    assert body["role_name"] == "Бармен"
    assert {"checks.edit", "checks.close", "tickets.status"} <= set(body["permissions"])
    # Но деньги и склад — не его: скидка и остатки остаются у старших.
    assert "checks.discount" not in body["permissions"]
    assert "stock.view" not in body["permissions"]
    # И попадает он в зал, а не на планшет: планшет живёт своим PIN.
    assert body["home"] == "/"


def test_waiter_sees_only_the_floor(client, hall):
    body = login(client, "1111")
    assert set(body["permissions"]) >= {"checks.edit", "checks.close"}
    assert "tickets.view" not in body["permissions"]
    assert "reports" not in body["permissions"]


def test_stock_is_for_owner_and_admin_only(client, hall):
    """Остаток на складе — это деньги на полке."""
    assert "stock.view" not in login(client, "444444")["permissions"]   # менеджер
    assert "stock.view" in login(client, "123456")["permissions"]       # владелец


# ------------------------------------------------------------- свой PIN ---
def test_own_pin_is_for_the_owner_and_manager(client, hall):
    """PIN в зале — не пароль от почты, а ключ от кассы.

    Официант, бармен и кухня свой PIN не меняют: забыл — новый выдаст
    менеджер, и это видно в журнале. Заведение должно знать, какой PIN у
    человека, иначе сбросить его по просьбе будет некому.
    """
    login(client, "1111")
    r = client.post("/api/auth/pin/change", json={"old": "1111", "new": "1212"})
    assert r.status_code == 403
    assert "менеджер" in r.json()["detail"]
    client.post("/api/auth/logout")
    assert client.post("/api/auth/pin", json={"pin": "1111"}).status_code == 200

    # А менеджер меняет.
    login(client, "444444")
    assert client.post(
        "/api/auth/pin/change", json={"old": "444444", "new": "441144"}
    ).status_code == 200
    client.post("/api/auth/logout")
    assert client.post("/api/auth/pin", json={"pin": "444444"}).status_code == 401
    assert client.post("/api/auth/pin", json={"pin": "441144"}).status_code == 200


def test_old_pin_is_required(client, hall):
    """Иначе любой, кто подошёл к незапертому планшету, работает под чужим именем."""
    login(client, "444444")
    r = client.post("/api/auth/pin/change", json={"old": "000000", "new": "121212"})
    assert r.status_code == 403
    client.post("/api/auth/logout")
    assert client.post("/api/auth/pin", json={"pin": "444444"}).status_code == 200


def test_new_pin_must_differ(client, hall):
    login(client, "444444")
    assert client.post(
        "/api/auth/pin/change", json={"old": "444444", "new": "444444"}
    ).status_code == 422


def test_own_pin_change_is_written_down(client, hall):
    login(client, "444444")
    client.post("/api/auth/pin/change", json={"old": "444444", "new": "441144"})
    journal = client.get("/api/admin/audit").json()
    assert any(r["action"] == "user.pin_self" and r["who"] == "Марина" for r in journal)


# ------------------------------------------------------- забытый PIN ------
def test_manager_resets_a_forgotten_pin(client, hall):
    """Официант без входа посреди смены не должен ждать администратора."""
    # Список сотрудников менеджеру не положен: id берём от владельца.
    login(client, "123456")
    anya = next(u for u in users(client) if u["name"] == "Аня")

    login(client, "444444")
    r = client.post(f"/api/admin/users/{anya['id']}/pin", json={"pin": "8181"})
    assert r.status_code == 200
    assert client.post("/api/auth/pin", json={"pin": "8181"}).status_code == 200


def test_waiter_cannot_reset_anyones_pin(client, hall):
    login(client, "123456")
    anya = next(u for u in users(client) if u["name"] == "Аня")
    login(client, "1111")
    assert client.post(
        f"/api/admin/users/{anya['id']}/pin", json={"pin": "8181"}
    ).status_code == 403


def test_nobody_touches_a_higher_role(client, hall):
    """Иначе менеджер сбрасывает PIN владельцу и заходит вместо него."""
    login(client, "123456")
    owner = next(u for u in users(client) if u["role"] == "owner")

    login(client, "444444")
    assert client.post(
        f"/api/admin/users/{owner['id']}/pin", json={"pin": "8181"}
    ).status_code == 403


def test_manager_cannot_create_staff(client, hall):
    """Сброс PIN — да, новые люди — нет: это разные права."""
    login(client, "444444")
    assert client.post(
        "/api/admin/users", json={"name": "Кто-то", "role": "waiter"}
    ).status_code == 403


def test_owner_can_hand_out_any_role(client, hall):
    login(client, "123456")
    made = client.post(
        "/api/admin/users", json={"name": "Второй владелец", "role": "owner", "pin": "909090"}
    )
    assert made.status_code == 201
    assert client.post("/api/auth/pin", json={"pin": "909090"}).json()["role"] == "owner"


def test_admin_cannot_make_an_owner(client, hall):
    login(client, "123456")
    admin = client.post(
        "/api/admin/users", json={"name": "Админ", "role": "admin", "pin": "707070"}
    ).json()
    assert admin["role"] == "admin"

    login(client, "707070")
    assert client.post(
        "/api/admin/users", json={"name": "Новый владелец", "role": "owner"}
    ).status_code == 403


def test_manager_sees_the_staff_list_but_cannot_change_it(client, hall):
    """Список нужен ради одного: найти того, кто забыл PIN."""
    login(client, "444444")
    listing = client.get("/api/admin/users")
    assert listing.status_code == 200
    assert any(u["name"] == "Аня" for u in listing.json())

    anya = next(u for u in listing.json() if u["name"] == "Аня")
    assert client.patch(
        f"/api/admin/users/{anya['id']}", json={"role": "manager"}
    ).status_code == 403
    assert client.post(
        "/api/admin/users", json={"name": "Новый", "role": "waiter"}
    ).status_code == 403


def test_waiter_does_not_see_the_staff_list(client, hall):
    login(client, "1111")
    assert client.get("/api/admin/users").status_code == 403
