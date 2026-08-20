"""Зависимости FastAPI: кто делает запрос и что ему разрешено.

Проверка прав живёт здесь и применяется на **каждом** эндпойнте, который
что-то меняет. Кнопки в интерфейсе прячутся отдельно и защитой не являются.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.permissions import can
from app.db import get_db
from app.models import Session, User, Venue
from app.services.auth import SESSION_COOKIE, resolve_session


def get_venue(db: DbSession = Depends(get_db)) -> Venue:
    venue = db.scalars(select(Venue).order_by(Venue.created_at)).first()
    if venue is None:
        raise HTTPException(status_code=503, detail="заведение не заведено")
    return venue


def current_identity(
    request: Request,
    db: DbSession = Depends(get_db),
) -> tuple[User, Session]:
    found = resolve_session(db, request.cookies.get(SESSION_COOKIE))
    if found is None:
        raise HTTPException(status_code=401, detail="нужен вход по PIN")
    db.commit()  # продление сессии при активности
    return found


def current_user(identity: tuple[User, Session] = Depends(current_identity)) -> User:
    return identity[0]


def require(permission: str) -> Callable[[User], User]:
    """`Depends(require('checks.close'))` — и эндпойнт закрыт на сервере.

    403, а не 404: прятать сам факт существования эндпойнта от собственного
    персонала смысла нет, а понятный отказ экономит смену.
    """

    def dependency(user: User = Depends(current_user)) -> User:
        if not can(user.role, permission):
            raise HTTPException(status_code=403, detail=f"нет права: {permission}")
        return user

    return dependency
