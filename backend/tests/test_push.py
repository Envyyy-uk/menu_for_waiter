"""Push — страховка на случай свёрнутого приложения."""

from sqlalchemy import select

from app.models import PushSubscription
from tests.test_floor import add, hall, login, open_check  # noqa: F401

SUB = {
    "endpoint": "https://push.example/abc",
    "keys": {"p256dh": "BF" + "a" * 85, "auth": "b" * 22},
}


def test_push_is_off_without_keys(client, hall):
    """Пустые ключи — приложение не должно просить разрешение зря."""
    login(client, "1111")
    body = client.get("/api/push/key").json()
    assert body["enabled"] is False
    assert body["public_key"] == ""


def test_subscription_follows_the_person_not_the_phone(client, db, venue, hall):
    """Тот же телефон в следующую смену достаётся другому официанту —
    подписка переезжает вместе с ним, а не звонит прошлому."""
    login(client, "1111")
    assert client.post("/api/push/subscribe", json=SUB).status_code == 200

    login(client, "444444")
    assert client.post("/api/push/subscribe", json=SUB).status_code == 200

    rows = db.scalars(select(PushSubscription)).all()
    assert len(rows) == 1
    from app.models import User

    assert db.get(User, rows[0].user_id).name == "Марина"


def test_unsubscribe_removes_it(client, db, hall):
    login(client, "1111")
    client.post("/api/push/subscribe", json=SUB)
    client.post("/api/push/unsubscribe", json=SUB)
    assert db.scalars(select(PushSubscription)).all() == []


def test_ready_does_not_fail_when_push_is_off(client, hall):
    """Push не ушёл — бармен всё равно нажал «Готово», и чек цел."""
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "2222")
    ticket = client.get("/api/station/queue").json()["tickets"][0]
    assert client.post(f"/api/station/tickets/{ticket['id']}/ready").status_code == 200

    login(client, "1111")
    assert len(client.get("/api/station/waiting").json()) == 1


def test_waiting_survives_a_missed_signal(client, hall):
    """Сигнал держится на состоянии, а не на событии: телефон был в кармане,
    сокет оборвался — список ждущих марок всё равно скажет правду."""
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    client.post(f"/api/checks/{check['id']}/send")

    login(client, "2222")
    ticket = client.get("/api/station/queue").json()["tickets"][0]
    client.post(f"/api/station/tickets/{ticket['id']}/ready")

    login(client, "1111")
    waiting = client.get("/api/station/waiting").json()
    assert [t["id"] for t in waiting] == [ticket["id"]]

    client.post(f"/api/station/tickets/{ticket['id']}/served")
    assert client.get("/api/station/waiting").json() == []
