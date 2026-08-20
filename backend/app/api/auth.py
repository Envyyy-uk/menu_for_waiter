from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from app.core.config import settings
from app.core.deps import current_identity, get_venue
from app.core.permissions import PERMISSIONS, can
from app.db import get_db
from app.models import ROLE_HOME, ROLE_NAMES, Session, User, Venue
from app.services.audit import record
from app.services.auth import (
    DEVICE_COOKIE,
    PIN_LENGTH,
    SESSION_COOKIE,
    AuthError,
    change_own_pin,
    close_session,
    ensure_device,
    login_with_pin,
    open_session,
    session_lifetime,
)

router = APIRouter(prefix="/api/auth", tags=["вход"])

# Устройство помнится год: это тот же планшет и тот же телефон, и заводить
# его заново каждую смену незачем.
DEVICE_COOKIE_DAYS = 365


class PinIn(BaseModel):
    pin: str = Field(min_length=PIN_LENGTH, max_length=PIN_LENGTH)


def _cookie(response: Response, name: str, value: str, seconds: int) -> None:
    response.set_cookie(
        name,
        value,
        max_age=seconds,
        httponly=True,
        samesite="lax",
        secure=settings.public_base_url.startswith("https://"),
        path="/",
    )


def me_payload(user: User) -> dict:
    return {
        "id": str(user.id),
        "name": user.name,
        "role": user.role,
        "role_name": ROLE_NAMES.get(user.role, user.role),
        "colour": user.colour,
        "home": ROLE_HOME.get(user.role, "/"),
        # Интерфейс прячет кнопки по этому списку. Это удобство, не защита:
        # каждый эндпойнт всё равно проверяет право сам.
        "permissions": sorted(p for p in PERMISSIONS if can(user.role, p)),
    }


@router.post("/pin")
def login_pin(
    body: PinIn,
    request: Request,
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> Response:
    """Ответ собирается вручную, а не через HTTPException, ради одной вещи:
    cookie устройства должна доехать и на неудачном входе.

    Иначе каждая ошибка заводит новое устройство, счётчик попыток всё время
    начинается с нуля, и блокировки после пяти попыток не существует."""
    device = ensure_device(
        db,
        venue.id,
        request.cookies.get(DEVICE_COOKIE),
        request.headers.get("user-agent"),
    )
    ip = request.client.host if request.client else None

    try:
        user = login_with_pin(db, venue.id, body.pin, device, ip)
    except AuthError as exc:
        db.commit()  # неудачную попытку надо сохранить, иначе блокировка не работает
        answer = JSONResponse(status_code=exc.status, content={"detail": exc.message})
        _cookie(answer, DEVICE_COOKIE, device.device_token, DEVICE_COOKIE_DAYS * 86400)
        return answer

    token = open_session(db, user, device)
    db.commit()
    answer = JSONResponse(me_payload(user))
    _cookie(answer, SESSION_COOKIE, token, int(session_lifetime(user.role).total_seconds()))
    _cookie(answer, DEVICE_COOKIE, device.device_token, DEVICE_COOKIE_DAYS * 86400)
    return answer


@router.post("/logout")
def logout(request: Request, response: Response, db: DbSession = Depends(get_db)) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        close_session(db, token)
        db.commit()
    # Устройство помнится дальше: вышел один официант — планшет не забыл сам себя.
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "ok"}


@router.get("/me")
def me(identity: tuple[User, Session] = Depends(current_identity)) -> dict:
    return me_payload(identity[0])


class ChangePinIn(BaseModel):
    old: str = Field(min_length=PIN_LENGTH, max_length=PIN_LENGTH)
    new: str = Field(min_length=PIN_LENGTH, max_length=PIN_LENGTH)


@router.post("/pin/change")
def change_pin(
    body: ChangePinIn,
    identity: tuple[User, Session] = Depends(current_identity),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Свой PIN человек меняет сам — знать старый обязательно.

    Забыл — это уже к менеджеру: сброс чужого PIN пишется в журнал, потому
    что это доступ к деньгам.
    """
    user = identity[0]
    try:
        change_own_pin(db, user, body.old, body.new)
    except AuthError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.message) from None

    record.write(
        db,
        venue_id=venue.id,
        user_id=user.id,
        action="user.pin_self",
        entity=f"user:{user.id}",
        after={"name": user.name},
    )
    db.commit()
    return {"status": "ok"}
