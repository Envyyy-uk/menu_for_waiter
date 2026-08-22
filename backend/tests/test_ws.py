"""Сокет реалтайма: отказ должен доехать до экрана."""

from tests.test_floor import hall, login  # noqa: F401


def test_socket_opens_for_a_signed_in_waiter(client, hall):
    login(client, "1111")
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "hello"


def _handshake(cookie: str | None = None) -> list[dict]:
    """Что сервер отвечает на рукопожатие — на уровне ASGI, без TestClient.

    Проверять это через TestClient нельзя: он показывает код закрытия и там,
    где браузер его никогда не увидит. А разница именно в этом — принят
    сокет до закрытия или нет.
    """
    import asyncio

    from app.main import app

    async def run() -> list[dict]:
        sent: list[dict] = []
        incoming: asyncio.Queue = asyncio.Queue()
        await incoming.put({"type": "websocket.connect"})
        headers = [(b"host", b"testserver")]
        if cookie:
            headers.append((b"cookie", cookie.encode()))
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "scheme": "ws",
            "path": "/ws",
            "raw_path": b"/ws",
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "subprotocols": [],
            "state": {},
        }
        async def receive() -> dict:
            return await incoming.get()

        async def send(message: dict) -> None:
            sent.append(message)

        await app(scope, receive, send)
        return sent

    return asyncio.run(run())


def test_refusal_reaches_the_screen_as_a_close_code(client, hall):
    """Отказ приходит закрытием принятого сокета, а не 403 на рукопожатии.

    403 браузер показывает как 1006 «обрыв связи»: экран уходит в вечные
    переподключения с надписью «нет связи» — вместо того, чтобы показать
    вход. Разница между «сети нет» и «войдите заново» здесь решающая, и
    видна она только по тому, был ли сокет принят до закрытия.
    """
    sent = _handshake()
    kinds = [m["type"] for m in sent]
    assert kinds == ["websocket.accept", "websocket.close"], kinds
    assert sent[-1].get("code") == 1008


def test_station_tablet_opens_the_socket_by_its_shift(client, hall):
    """Планшету личный вход не нужен: у него смена станции."""
    client.post("/api/station/shift/open", json={"pin": "2222"})
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
