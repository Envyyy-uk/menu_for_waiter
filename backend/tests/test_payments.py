"""Список оплат: за что именно взяли деньги.

Отчёт отвечает «сколько всего», этот список — «за что». Его открывают, когда
касса не сошлась или гость вернулся со словами «мне посчитали лишнее».
"""

from tests.test_floor import add, hall, login, open_check  # noqa: F401


def closed_check(client, hall, *, discount=0, reason=None):
    login(client, "1111")
    check = open_check(client, hall, guests=3)
    add(client, check["id"], hall["mojito"], qty=2)          # £32.00
    check = client.post(f"/api/checks/{check['id']}/send").json()
    if discount:
        login(client, "444444")
        check = client.post(
            f"/api/checks/{check['id']}/discount",
            json={"discount_pence": discount, "reason": reason},
        ).json()
        login(client, "1111")
    due = check["due_pence"]
    return client.post(
        f"/api/checks/{check['id']}/close",
        json={"payments": [{"method": "cash", "amount_pence": due, "tendered_pence": due + 500}]},
    ).json()


def test_payments_show_what_was_inside(client, hall):
    closed_check(client, hall)
    login(client, "123456")
    body = client.get("/api/admin/payments").json()
    assert body["checks"] == 1
    row = body["rows"][0]
    assert row["total_pence"] == 3200
    assert row["waiter"] == "Аня"
    assert row["guests"] == 3
    assert row["payments"][0]["method"] == "cash"
    # Сдача видна: касса считала её, а не официант в уме.
    assert row["payments"][0]["tendered_pence"] == 3700
    assert row["items"][0]["name"] == "Mojito"
    assert row["items"][0]["qty"] == 2


def test_discount_is_visible_with_its_reason(client, hall):
    closed_check(client, hall, discount=600, reason="постоянный гость")
    login(client, "123456")
    row = client.get("/api/admin/payments").json()["rows"][0]
    assert row["discount_pence"] == 600
    assert row["discount_reason"] == "постоянный гость"
    assert row["subtotal_pence"] == 3200
    assert row["total_pence"] == 2600
    assert client.get("/api/admin/payments").json()["discount_pence"] == 600


def test_cancelled_before_paying_stays_visible(client, hall):
    """Гость помнит одну сумму, чек показывает другую — вот почему."""
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    add(client, check["id"], hall["pizza"])
    check = client.post(f"/api/checks/{check['id']}/send").json()
    pizza = next(i for i in check["items"] if i["name"] != "Mojito")

    login(client, "444444")
    check = client.post(
        f"/api/checks/{check['id']}/items/{pizza['id']}/cancel",
        json={"reason": "гость передумал"},
    ).json()
    client.post(
        f"/api/checks/{check['id']}/close",
        json={"payments": [{"method": "card", "amount_pence": check["due_pence"]}]},
    )

    login(client, "123456")
    row = client.get("/api/admin/payments").json()["rows"][0]
    assert [i["name"] for i in row["items"]] == ["Mojito"]
    assert row["cancelled"][0]["reason"] == "гость передумал"


def test_open_checks_are_not_payments(client, hall):
    """Незакрытый чек — ещё не деньги."""
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "123456")
    assert client.get("/api/admin/payments").json()["checks"] == 0


def test_waiter_does_not_see_the_payments(client, hall):
    """Кто закрыл свой чек, знает свою выручку. Чужую — нет."""
    closed_check(client, hall)
    login(client, "1111")
    assert client.get("/api/admin/payments").status_code == 403


def test_manager_sees_the_payments(client, hall):
    """Спорный чек менеджер разбирает сам, не дожидаясь администратора."""
    closed_check(client, hall)
    login(client, "444444")
    assert client.get("/api/admin/payments").status_code == 200
