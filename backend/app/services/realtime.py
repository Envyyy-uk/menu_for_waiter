"""Реалтайм: сигнал «что-то изменилось».

Событие здесь — **не состояние**, а повод перечитать. Получив его, экран
запрашивает свой список у сервера целиком. Так же он поступает после обрыва
связи: полная перезагрузка состояния, а не доигрывание пропущенных событий.
Доигрывание означало бы, что одно потерянное событие тихо оставляет планшет
устаревшим — а это ровно то, чего допустить нельзя.

Источник правды — Postgres. Это только способ не ждать следующего опроса.

Подписка адресная: планшет бара не должен просыпаться от каждого чека в зале,
а телефон официанта — от чужих марок.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger("realtime")

# Очередь на каждое подключение. Размер ограничен намеренно: если планшет не
# успевает, мы не растём в память, а выбрасываем сигнал — следующий всё равно
# заставит перечитать всё.
QUEUE_SIZE = 32

# Каналы. Строка вида "station:bar" или "waiter:<uuid>".
#
# "all" слышат все — туда идёт только то, что касается всех сразу: стоп-лист.
# "floor" — изменения чеков; станции туда не подписаны намеренно, иначе
# планшет бара перерисовывался бы на каждую позицию, набранную в зале.
CHANNEL_ALL = "all"
CHANNEL_FLOOR = "floor"
# Склад слышат те, кто за него отвечает. Официанту знать, что кончается
# вермут, незачем — а владельцу нужно, и сразу.
CHANNEL_STOCK = "stock"


def station_channel(station: str) -> str:
    return f"station:{station}"


def waiter_channel(user_id) -> str:
    return f"waiter:{user_id}"


class _Hub:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.subscribers: dict[asyncio.Queue, set[str]] = {}

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def subscribe(self, channels: set[str]) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.subscribers[queue] = set(channels) | {CHANNEL_ALL}
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.pop(queue, None)

    def count(self, channel: str | None = None) -> int:
        if channel is None:
            return len(self.subscribers)
        return sum(1 for chans in self.subscribers.values() if channel in chans)

    def publish(self, channel: str, event: dict[str, Any]) -> None:
        """Зовётся из синхронных обработчиков — они живут в пуле потоков,
        поэтому кладём в очередь через `call_soon_threadsafe`."""
        if self.loop is None or not self.subscribers:
            return
        payload = {**event, "channel": channel}
        for queue, channels in list(self.subscribers.items()):
            if channel not in channels:
                continue
            try:
                self.loop.call_soon_threadsafe(self._put, queue, payload)
            except RuntimeError:  # цикл уже остановлен — сервер выключается
                return

    @staticmethod
    def _put(queue: asyncio.Queue, event: dict[str, Any]) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("очередь переполнена, теряем %s", event.get("type"))


hub = _Hub()

bind_loop = hub.bind_loop
subscribe = hub.subscribe
unsubscribe = hub.unsubscribe
publish = hub.publish
