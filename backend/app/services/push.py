"""Web Push — страховка на случай, когда приложение свёрнуто.

Главный сигнал живёт в открытом приложении: он идёт по медиаканалу и потому
слышен даже при выключенном звонке. Push — второй уровень, и он честно
подчиняется настройкам телефона: в беззвучном режиме система звук выключит,
и обойти это из браузера нельзя.

Отправка идёт в отдельном потоке и никогда не роняет запрос: если push не
ушёл, бармен всё равно нажал «Готово», и чек от этого не портится.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from pywebpush import WebPushException, webpush
from sqlalchemy import select

from app.core.config import settings
from app.db import SessionLocal
from app.models import PushSubscription, utcnow

log = logging.getLogger("push")

# Дольше этого ждать нечего: сигнал, который дошёл через минуту, уже не сигнал.
TIMEOUT_SECONDS = 8


def enabled() -> bool:
    return settings.push_enabled


def _send_one(row_id, endpoint: str, p256dh: str, auth: str, payload: dict[str, Any]) -> None:
    try:
        webpush(
            subscription_info={
                "endpoint": endpoint,
                "keys": {"p256dh": p256dh, "auth": auth},
            },
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            timeout=TIMEOUT_SECONDS,
        )
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        # 404 и 410 означают, что подписки больше нет: телефон переустановили
        # или приложение удалили. Держать её дальше незачем.
        with SessionLocal() as db:
            row = db.get(PushSubscription, row_id)
            if row is None:
                return
            if status in (404, 410):
                db.delete(row)
            else:
                row.failed_at = utcnow()
            db.commit()
        log.warning("push не ушёл (%s): %s", status, exc)
    except Exception:  # noqa: BLE001 — сеть до push-сервиса это не наша сеть
        log.warning("push не ушёл", exc_info=True)


def notify(user_id, payload: dict[str, Any]) -> None:
    """Разослать на все устройства человека. Возврат сразу, отправка в фоне."""
    if not enabled():
        return
    with SessionLocal() as db:
        rows = db.scalars(
            select(PushSubscription).where(PushSubscription.user_id == user_id)
        ).all()
        targets = [(r.id, r.endpoint, r.p256dh, r.auth) for r in rows]

    for row_id, endpoint, p256dh, auth in targets:
        threading.Thread(
            target=_send_one,
            args=(row_id, endpoint, p256dh, auth, payload),
            daemon=True,
        ).start()
