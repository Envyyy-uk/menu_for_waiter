"""Закрытие чека: карта, наличные, пополам. И то, чего делать нельзя."""

from tests.test_floor import add, hall, login, open_check  # noqa: F401


def sent_check(client, hall, item="mojito", qty=1):
    check = open_check(client, hall)
    add(client, check["id"], hall[item], qty=qty)
    return client.post(f"/api/checks/{check['id']}/send").json()


def test_close_with_cash(client, hall):
    login(client, "1111")
    check = sent_check(client, hall)          # Мохито £16.00
    body = client.post(
        f"/api/checks/{check['id']}/close",
        json={"payments": [{"method": "cash", "amount_pence": 1600, "tendered_pence": 2000}]},
    )
    assert body.status_code == 200, body.text
    closed = body.json()
    assert closed["status"] == "closed"
    assert closed["due_pence"] == 0
    assert closed["payments"][0]["method"] == "cash"
    # Сдачу считает касса, а не официант в уме: сколько дали, записано.
    assert closed["payments"][0]["tendered_pence"] == 2000

    # Закрытый стол снова свободен.
    tables = client.get("/api/tables").json()
    assert next(t for t in tables if t["id"] == hall["table"])["checks"] == []


def test_close_split_between_card_and_cash(client, hall):
    login(client, "1111")
    check = sent_check(client, hall, qty=2)   # £32.00
    closed = client.post(
        f"/api/checks/{check['id']}/close",
        json={
            "payments": [
                {"method": "card", "amount_pence": 2000},
                {"method": "cash", "amount_pence": 1200},
            ]
        },
    ).json()
    assert closed["status"] == "closed"
    assert {p["method"] for p in closed["payments"]} == {"card", "cash"}


def test_sum_must_match_exactly(client, hall):
    """Недобор оставил бы долг, которого никто не увидит."""
    login(client, "1111")
    check = sent_check(client, hall)
    r = client.post(
        f"/api/checks/{check['id']}/close",
        json={"payments": [{"method": "card", "amount_pence": 1000}]},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["due_pence"] == 1600


def test_cannot_close_with_unsent_items(client, hall):
    """Иначе бар узнаёт о заказе после того, как гость ушёл."""
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    r = client.post(
        f"/api/checks/{check['id']}/close",
        json={"payments": [{"method": "card", "amount_pence": 1600}]},
    )
    assert r.status_code == 409


def test_cannot_close_empty_check(client, hall):
    login(client, "1111")
    check = open_check(client, hall)
    r = client.post(
        f"/api/checks/{check['id']}/close",
        json={"payments": [{"method": "cash", "amount_pence": 100}]},
    )
    assert r.status_code == 409


def test_closed_check_does_not_accept_items(client, hall):
    login(client, "1111")
    check = sent_check(client, hall)
    client.post(
        f"/api/checks/{check['id']}/close",
        json={"payments": [{"method": "card", "amount_pence": 1600}]},
    )
    assert add(client, check["id"], hall["mojito"]).status_code == 409


def test_discount_is_a_manager_decision(client, hall):
    login(client, "1111")
    check = sent_check(client, hall)
    assert (
        client.post(
            f"/api/checks/{check['id']}/discount", json={"discount_pence": 600}
        ).status_code
        == 403
    )

    login(client, "4444")
    with_discount = client.post(
        f"/api/checks/{check['id']}/discount",
        json={"discount_pence": 600, "reason": "постоянный гость"},
    ).json()
    assert with_discount["total_pence"] == 1000
    assert with_discount["due_pence"] == 1000


def test_discount_cannot_exceed_the_bill(client, hall):
    """Заведение не доплачивает гостю."""
    login(client, "1111")
    check = sent_check(client, hall)
    login(client, "4444")
    r = client.post(
        f"/api/checks/{check['id']}/discount", json={"discount_pence": 9999}
    )
    assert r.status_code == 422


def test_draft_is_removed_by_the_waiter_but_sent_needs_a_manager(client, hall):
    login(client, "1111")
    check = open_check(client, hall)
    check = add(client, check["id"], hall["mojito"]).json()
    draft = check["items"][0]["id"]
    # Свой черновик официант убирает сам.
    after = client.post(
        f"/api/checks/{check['id']}/items/{draft}/cancel", json={}
    ).json()
    assert after["items"] == []

    check = add(client, check["id"], hall["mojito"]).json()
    check = client.post(f"/api/checks/{check['id']}/send").json()
    sent = check["items"][0]["id"]
    assert (
        client.post(
            f"/api/checks/{check['id']}/items/{sent}/cancel", json={"reason": "передумали"}
        ).status_code
        == 403
    )

    login(client, "4444")
    after = client.post(
        f"/api/checks/{check['id']}/items/{sent}/cancel", json={"reason": "передумали"}
    ).json()
    # Отправленное не исчезает молча: остаётся в чеке отменённым и с причиной.
    assert after["items"][0]["status"] == "cancelled"
    assert after["items"][0]["cancel_reason"] == "передумали"
    assert after["total_pence"] == 0


def test_cancelled_item_stays_visible_on_the_station(client, hall):
    """Бармен уже мог начать делать — об отмене он должен узнать."""
    login(client, "1111")
    check = sent_check(client, hall)
    item = check["items"][0]["id"]

    login(client, "4444")
    client.post(f"/api/checks/{check['id']}/items/{item}/cancel", json={"reason": "ушли"})

    login(client, "2222")
    ticket = client.get("/api/station/queue").json()["tickets"][0]
    assert ticket["items"] == []
    assert ticket["cancelled"][0]["name"] == "Mojito"


def test_sent_item_cannot_be_edited(client, hall):
    login(client, "1111")
    check = sent_check(client, hall)
    item = check["items"][0]["id"]
    r = client.patch(f"/api/checks/{check['id']}/items/{item}", json={"qty": 5})
    assert r.status_code == 409


def test_stop_list_blocks_ordering(client, hall, db):
    """Кончилось у бара — и оно кончилось для всех, сразу."""
    login(client, "2222")
    r = client.post(f"/api/menu/{hall['mojito']}/state", json={"state": "off"})
    assert r.status_code == 200

    login(client, "1111")
    check = open_check(client, hall)
    r = add(client, check["id"], hall["mojito"])
    assert r.status_code == 409
    assert "стоп" in r.json()["detail"]["message"]
