"""Подписка телефона на push."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.config import settings
from app.core.deps import current_user, get_venue
from app.db import get_db
from app.models import PushSubscription, User, Venue
from app.services import push

router = APIRouter(prefix="/api/push", tags=["уведомления"])


class Keys(BaseModel):
    p256dh: str
    auth: str


class SubscribeIn(BaseModel):
    endpoint: str
    keys: Keys


@router.get("/key")
def key(user: User = Depends(current_user)) -> dict:
    """Пустой ключ = push выключён. Приложение тогда не просит разрешения
    зря — лишний системный вопрос в первый же день учит нажимать «нет»."""
    return {"enabled": push.enabled(), "public_key": settings.vapid_public_key}


@router.post("/subscribe")
def subscribe(
    body: SubscribeIn,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    row = db.scalars(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    ).first()
    if row is None:
        row = PushSubscription(venue_id=venue.id, endpoint=body.endpoint)
        db.add(row)
    # Один и тот же телефон может достаться другому официанту в следующую
    # смену — подписка переезжает вместе с ним, а не звонит прошлому.
    row.user_id = user.id
    row.p256dh = body.keys.p256dh
    row.auth = body.keys.auth
    row.failed_at = None
    db.commit()
    return {"status": "ok"}


@router.post("/unsubscribe")
def unsubscribe(
    body: SubscribeIn,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> dict:
    row = db.scalars(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    ).first()
    if row is not None:
        db.delete(row)
        db.commit()
    return {"status": "ok"}
