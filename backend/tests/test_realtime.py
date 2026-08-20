"""Реалтайм: сигнал «перечитай» доезжает туда, куда должен, и только туда."""

import asyncio

from app.services import realtime
from tests.test_floor import add, hall, login, open_check  # noqa: F401


def test_channels_are_addressed():
    """Планшет бара не просыпается от каждого чека в зале."""
    realtime.hub.bind_loop(asyncio.new_event_loop())
    bar = realtime.subscribe({realtime.station_channel("bar")})
    kitchen = realtime.subscribe({realtime.station_channel("kitchen")})
    try:
        realtime.hub.publish(realtime.station_channel("bar"), {"type": "ticket.new"})
        realtime.hub.loop.run_until_complete(asyncio.sleep(0))
        assert bar.qsize() == 1
        assert kitchen.qsize() == 0
    finally:
        realtime.unsubscribe(bar)
        realtime.unsubscribe(kitchen)
        realtime.hub.loop.close()
        realtime.hub.loop = None


def test_station_wakes_up_when_the_waiter_sends(client, hall):
    """Пока сигнал не дошёл, заказ существует только в телефоне официанта."""
    login(client, "2222")  # бармен — его сессия уйдёт в рукопожатие сокета
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "hello"

        login(client, "1111")  # официант перехватывает cookie сессии
        check = open_check(client, hall)
        add(client, check["id"], hall["mojito"])
        client.post(f"/api/checks/{check['id']}/send")

        # Мимо ping-ов: тишина тоже сообщение, но нам нужно событие.
        for _ in range(10):
            event = socket.receive_json()
            if event["type"] != "ping":
                break
        assert event["type"] == "ticket.new"
        assert event["station"] == "bar"
        assert event["table"] == "1"


def test_waiter_hears_ready(client, hall):
    """Ради этого события существует половина системы."""
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    client.post(f"/api/checks/{check['id']}/send")

    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "hello"

        login(client, "2222")
        ticket = client.get("/api/station/queue").json()["tickets"][0]
        client.post(f"/api/station/tickets/{ticket['id']}/ready")

        for _ in range(10):
            event = socket.receive_json()
            if event["type"] == "ticket.ready":
                break
        assert event["type"] == "ticket.ready"
        assert event["table"] == "1"
        assert event["station_name"] == "Бар"


def test_socket_without_pin_is_closed(client):
    """Экран должен показать вход, а не молчаливый пустой список."""
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws") as socket:
            socket.receive_json()
    assert exc.value.code == 1008


def test_station_is_not_woken_by_every_check_in_the_hall(client, hall):
    """Планшет бара не должен перерисовываться на каждую набранную позицию."""
    login(client, "2222")
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "hello"

        login(client, "1111")
        check = open_check(client, hall)
        add(client, check["id"], hall["mojito"])

        # Три сообщения подряд — и все они должны быть тишиной.
        assert [socket.receive_json()["type"] for _ in range(3)] == ["ping"] * 3
