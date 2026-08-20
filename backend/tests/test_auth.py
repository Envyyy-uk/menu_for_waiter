from app.core.config import settings


def login(client, pin: str):
    return client.post("/api/auth/pin", json={"pin": pin})


def test_pin_opens_own_app(client, make_user):
    make_user("Аня", role="waiter", pin="2468")
    r = login(client, "2468")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Аня"
    assert body["role_name"] == "Официант"
    # После PIN человек попадает сразу в своё приложение, а не в общее меню.
    assert body["home"] == "/"
    assert "checks.edit" in body["permissions"]
    assert "users.manage" not in body["permissions"]


def test_bar_lands_in_the_hall(client, make_user):
    """За стойкой сидят гости, и заказ у них принимает бармен сам.

    Планшет с одними марками живёт отдельно и открывается своим PIN станции,
    поэтому бармена сюда не отправляем.
    """
    make_user("Игорь", role="bar", pin="3579")
    body = login(client, "3579").json()
    assert body["home"] == "/"
    assert {"tickets.status", "checks.edit", "checks.close"} <= set(body["permissions"])
    # Но скидка и склад — не его.
    assert "checks.discount" not in body["permissions"]
    assert "stock.view" not in body["permissions"]


def test_kitchen_lands_on_the_station(client, make_user):
    make_user("Пётр", role="kitchen", pin="3580")
    body = login(client, "3580").json()
    assert body["home"] == "/station/"
    assert "checks.edit" not in body["permissions"]


def test_wrong_pin_is_rejected(client, make_user):
    make_user("Аня", pin="2468")
    r = login(client, "0000")
    assert r.status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_five_wrong_attempts_lock_the_device(client, make_user):
    make_user("Аня", pin="2468")
    for _ in range(settings.pin_max_attempts):
        assert login(client, "0000").status_code == 401
    # Шестая попытка — уже ожидание, и даже с верным PIN.
    assert login(client, "0000").status_code == 429
    assert login(client, "2468").status_code == 429


def test_inactive_staff_cannot_enter(client, make_user):
    make_user("Уволенный", pin="4321", active=False)
    assert login(client, "4321").status_code == 403


def test_logout_closes_session_but_remembers_device(client, make_user):
    make_user("Аня", pin="2468")
    login(client, "2468")
    assert client.get("/api/auth/me").status_code == 200

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    # Планшет не забыл сам себя: устройство остаётся, вход снова работает.
    assert "device" in client.cookies
    assert login(client, "2468").status_code == 200


def test_pin_is_unique_in_venue(db, venue, make_user):
    import pytest

    from app.models import User
    from app.services.auth import AuthError, issue_pin

    make_user("Аня", pin="2468")
    other = User(venue_id=venue.id, name="Боря", role="waiter")
    db.add(other)
    db.flush()
    with pytest.raises(AuthError):
        issue_pin(db, other, "2468")


def test_failed_attempt_keeps_the_same_device(client, make_user):
    """Регрессия: cookie устройства должна доезжать и на неудачном входе.

    Пока она терялась, каждая ошибка заводила новое устройство, счётчик
    начинался с нуля — и блокировки после пяти попыток не существовало.
    """
    make_user("Аня", pin="2468")
    login(client, "0000")
    first = client.cookies["device"]
    login(client, "0000")
    assert client.cookies["device"] == first


def test_clearing_device_cookie_does_not_reset_the_counter(client, make_user):
    """Подбор PIN не должен стоить двух нажатий в настройках браузера."""
    make_user("Аня", pin="2468")
    for _ in range(settings.pin_max_attempts):
        login(client, "0000")
    client.cookies.delete("device")
    assert login(client, "0000").status_code == 429


# ------------------------------------------------------- длина PIN по роли --
def test_hall_keeps_four_digits(client, make_user):
    """В зале вход без кнопки «войти»: набрал четыре — уже вошёл."""
    make_user("Аня", role="waiter", pin="1379")
    body = login(client, "1379").json()
    assert body["pin_length"] == 4


def test_admin_pin_is_six_digits(client, make_user):
    """Из админки правят цены, роли и склад, и видно все оплаты.

    Четыре цифры — десять тысяч вариантов; шесть — миллион.
    """
    make_user("Ольга", role="admin", pin="314159")
    body = login(client, "314159").json()
    assert body["pin_length"] == 6
    assert body["home"] == "/admin/"


def test_admin_cannot_take_a_short_pin(client, make_user):
    from app.services.auth import AuthError

    try:
        make_user("Короткий", role="manager", pin="1379")
    except AuthError as exc:
        assert "цифр" in exc.message
    else:
        raise AssertionError("менеджеру выдали PIN из четырёх цифр")


def test_waiter_cannot_take_a_long_pin(client, make_user):
    """Длина не «не меньше», а «ровно»: экран зала принимает четыре и не ждёт."""
    from app.services.auth import AuthError

    try:
        make_user("Длинный", role="waiter", pin="314159")
    except AuthError as exc:
        assert "цифр" in exc.message
    else:
        raise AssertionError("официанту выдали PIN из шести цифр")


def test_role_change_hands_out_a_new_pin(client, make_user):
    """Переезд из зала в админку меняет длину PIN.

    Оставить старый значит запереть человека снаружи: экран админки ждёт
    шесть цифр и четырьмя не откроется.
    """
    make_user("Аня", role="waiter", pin="1379")
    login(client, settings.seed_admin_pin)
    anya = next(u for u in client.get("/api/admin/users").json() if u["name"] == "Аня")

    out = client.patch(f"/api/admin/users/{anya['id']}", json={"role": "manager"}).json()
    assert out["role"] == "manager"
    assert len(out["pin"]) == 6
    assert out["pin_length"] == 6

    # Старый PIN больше не пускает, новый пускает.
    assert login(client, "1379").status_code == 401
    assert login(client, out["pin"]).json()["role"] == "manager"


def test_role_change_inside_the_hall_keeps_the_pin(client, make_user):
    """Официант стал барменом — PIN у него тот же, длина не поменялась."""
    make_user("Игорь", role="waiter", pin="1379")
    login(client, settings.seed_admin_pin)
    igor = next(u for u in client.get("/api/admin/users").json() if u["name"] == "Игорь")

    out = client.patch(f"/api/admin/users/{igor['id']}", json={"role": "bar"}).json()
    assert "pin" not in out
    assert login(client, "1379").json()["role"] == "bar"
