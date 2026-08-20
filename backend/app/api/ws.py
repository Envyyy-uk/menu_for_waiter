"""WebSocket: сигнал «перечитай».

Сервер шлёт ping каждые три секунды. Это не косметика: **тишина — тоже
сообщение**. Клиент меряет время от последнего сообщения и, когда оно уходит
за десять секунд, кричит. Без ping-ов молчащий сокет и рабочий сокет
выглядят одинаково.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.permissions import can
from app.db import SessionLocal
from app.models import ROLE_BAR, ROLE_KITCHEN, STATION_BAR, STATION_KITCHEN
from app.services import realtime
from app.services.auth import SESSION_COOKIE, resolve_session

router = APIRouter(tags=["реалтайм"])
log = logging.getLogger("ws")

PING_SECONDS = 3
ROLE_STATION = {ROLE_BAR: STATION_BAR, ROLE_KITCHEN: STATION_KITCHEN}


def _channels(token: str | None) -> set[str] | None:
    """На что подписан этот человек. None — вход не подтверждён.

    Подписка адресная: планшет бара не просыпается от каждого чека в зале,
    а телефон официанта — от чужих марок.
    """
    if not token:
        return None
    with SessionLocal() as db:
        found = resolve_session(db, token)
        if found is None:
            return None
        db.commit()
        user = found[0]

        channels: set[str] = set()
        if can(user.role, "checks.view"):
            channels.add(realtime.CHANNEL_FLOOR)
            channels.add(realtime.waiter_channel(user.id))
        if can(user.role, "tickets.view"):
            station = ROLE_STATION.get(user.role)
            if station:
                channels.add(realtime.station_channel(station))
            else:
                # Менеджер видит обе станции: он и подменяет, и разбирается.
                channels.add(realtime.station_channel(STATION_BAR))
                channels.add(realtime.station_channel(STATION_KITCHEN))
        return channels


@router.websocket("/ws")
async def socket(websocket: WebSocket) -> None:
    token = websocket.cookies.get(SESSION_COOKIE)
    channels = await asyncio.to_thread(_channels, token)
    if channels is None:
        # 1008 — policy violation. Экран должен показать вход, а не молчаливый
        # пустой список.
        await websocket.close(code=1008)
        return

    await websocket.accept()
    queue = realtime.subscribe(channels)
    try:
        # Первое сообщение сразу: экран не должен ждать три секунды, чтобы
        # понять, что связь есть.
        await websocket.send_json({"type": "hello"})
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=PING_SECONDS)
            except asyncio.TimeoutError:
                event = {"type": "ping"}
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 — обрыв сети на планшете это норма
        log.debug("сокет закрылся", exc_info=True)
    finally:
        realtime.unsubscribe(queue)
        with contextlib.suppress(Exception):
            await websocket.close()
