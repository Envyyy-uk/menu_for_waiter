"""Вход в систему: только личный PIN.

В зале пароль не работает. Официант вводит его пятьдесят раз за смену и через
день просто не выходит из сессии — то есть защиты не остаётся вовсе. Поэтому
здесь один способ входа, и он рассчитан на мокрые руки и чужой планшет.

PIN — слабый фактор (четыре-шесть цифр). Держат его три вещи:

* счётчик неудач ведётся на устройстве — кто именно ошибся, мы не знаем;
* после пяти подряд устройство ждёт пятнадцать минут;
* всё, что двигает деньги, пишется в журнал с именем того, кто это сделал.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.config import settings
from app.core.security import hash_secret, new_token, token_fingerprint, verify_secret
from app.models import Device, Session, User, utcnow
from app.models.user import ROLE_ADMIN, ROLE_MANAGER, ROLE_OWNER
from app.services.audit import record

SESSION_COOKIE = "session"
DEVICE_COOKIE = "device"

# Длина PIN зависит от роли, и это не украшение.
#
# В зале четыре цифры: набрал — и уже вошёл, без кнопки «войти». Лишнее
# нажатие пятьдесят раз за смену стоит дороже, чем кажется, а к деньгам
# заведения этот вход не ведёт: официант видит свои столы.
#
# В админке шесть: оттуда правят цены, роли, склад и видно все оплаты.
# Четыре цифры — это десять тысяч вариантов, и подобрать их можно за вечер,
# если никто не смотрит на счётчик. Шесть — миллион, и это уже другой
# разговор. Отдельная длина заодно значит отдельный PIN: тот, кем открывают
# админку, не тот, которым официант входит в зал.
#
# Внутри каждого экрана длина всё равно одна и та же, поэтому вход остаётся
# без кнопки «войти»: набрал шесть — вошёл.
PIN_LENGTH = 4
ADMIN_PIN_LENGTH = 6
# Кому нужен длинный PIN: те, кто открывает админку.
ADMIN_PIN_ROLES = (ROLE_OWNER, ROLE_ADMIN, ROLE_MANAGER)


def pin_length(role: str) -> int:
    return ADMIN_PIN_LENGTH if role in ADMIN_PIN_ROLES else PIN_LENGTH


def pin_words(length: int) -> str:
    return {4: "четыре цифры", 6: "шесть цифр"}.get(length, f"{length} цифр")



class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.message = message
        self.status = status


def session_lifetime(role: str) -> timedelta:
    minutes = (
        settings.manager_session_minutes
        if role in (ROLE_ADMIN, ROLE_MANAGER)
        else settings.staff_session_minutes
    )
    return timedelta(minutes=minutes)


# ------------------------------------------------------------- устройство ---
def ensure_device(db: DbSession, venue_id, token: str | None, user_agent: str | None) -> Device:
    """Устройство заводится само при первом обращении.

    Регистрировать планшеты руками — лишний шаг, на котором смена встаёт.
    Устройство нужно не как пропуск, а как то, на чём считается счётчик
    неудачных PIN и куда потом уходит push.
    """
    if token:
        device = db.scalars(
            select(Device).where(Device.venue_id == venue_id, Device.device_token == token)
        ).first()
        if device is not None:
            device.last_seen_at = utcnow()
            if user_agent:
                device.user_agent = user_agent
            return device

    device = Device(
        venue_id=venue_id,
        device_token=secrets.token_urlsafe(24),
        user_agent=user_agent,
        last_seen_at=utcnow(),
    )
    db.add(device)
    db.flush()
    return device


def _failure_keys(device: Device, ip: str | None) -> list[str]:
    """На чём считаем неудачи.

    На устройстве — потому что мы не знаем, кто именно ошибся, и вешать
    счётчик на случайного сотрудника нельзя. И на адресе тоже: cookie
    устройства чистится в два нажатия, и без второго счётчика перебор PIN
    ничего не стоит.
    """
    keys = [f"device:{device.id}"]
    if ip:
        keys.append(f"ip:{ip}")
    return keys


def pin_attempts_exhausted(db: DbSession, venue_id, device: Device, ip: str | None) -> bool:
    """Ждёт ли этот вход. Считается по окну в `pin_lockout_minutes`."""
    window = utcnow() - timedelta(minutes=settings.pin_lockout_minutes)
    for key in _failure_keys(device, ip):
        recent = record.count_recent(
            db, venue_id, action="pin.failed", entity=key, since=window
        )
        if recent >= settings.pin_max_attempts:
            return True
    return False


# ------------------------------------------------------------------ сессия ---
def open_session(db: DbSession, user: User, device: Device | None = None) -> str:
    """Возвращает токен открытым текстом — единственный раз, когда он
    существует вне cookie. В базе лежит только хеш."""
    token = new_token()
    db.add(
        Session(
            venue_id=user.venue_id,
            user_id=user.id,
            device_id=device.id if device else None,
            token_hash=token_fingerprint(token),
            expires_at=utcnow() + session_lifetime(user.role),
            last_seen_at=utcnow(),
        )
    )
    return token


def close_session(db: DbSession, token: str) -> None:
    row = db.scalars(select(Session).where(Session.token_hash == token_fingerprint(token))).first()
    if row is not None:
        db.delete(row)


def resolve_session(db: DbSession, token: str | None) -> tuple[User, Session] | None:
    if not token:
        return None
    row = db.scalars(select(Session).where(Session.token_hash == token_fingerprint(token))).first()
    if row is None:
        return None
    if row.expires_at <= utcnow():
        db.delete(row)
        db.commit()
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.active:
        return None
    # Сессия продлевается при активности: смена длиннее таймера, а выгонять
    # официанта посреди заказа хуже, чем держать сессию открытой.
    row.last_seen_at = utcnow()
    row.expires_at = utcnow() + session_lifetime(user.role)
    return user, row


# -------------------------------------------------------------------- вход ---
def login_with_pin(db: DbSession, venue_id, pin: str, device: Device, ip: str | None = None) -> User:
    if pin_attempts_exhausted(db, venue_id, device, ip):
        raise AuthError(
            f"Слишком много попыток. Подождите {settings.pin_lockout_minutes} минут.",
            status=429,
        )

    now = utcnow()
    candidates = db.scalars(
        select(User).where(User.venue_id == venue_id, User.pin_hash.is_not(None))
    ).all()

    for user in candidates:
        if not verify_secret(user.pin_hash, pin):
            continue
        if not user.active:
            raise AuthError("Учётная запись отключена", status=403)
        if user.pin_locked_until and user.pin_locked_until > now:
            raise AuthError("PIN заблокирован, попробуйте позже", status=429)
        user.pin_failed_attempts = 0
        user.pin_locked_until = None
        device.last_seen_at = now
        return user

    _register_failed_pin(db, venue_id, device, ip)
    raise AuthError("Неверный PIN")


def _register_failed_pin(db: DbSession, venue_id, device: Device, ip: str | None) -> None:
    for key in _failure_keys(device, ip):
        record.write(
            db,
            venue_id=venue_id,
            user_id=None,
            action="pin.failed",
            entity=key,
            after={"device": str(device.id)},
        )


def change_own_pin(db: DbSession, user: User, old: str, new: str) -> None:
    """Смена своего PIN. Старый спрашивается обязательно.

    Без него любой, кто подошёл к незапертому планшету, менял бы чужой PIN на
    свой — и с этой минуты работал бы под чужим именем.
    """
    if not verify_secret(user.pin_hash, old):
        raise AuthError("Старый PIN не подходит", status=403)
    if old == new:
        raise AuthError("Новый PIN совпадает со старым", status=422)
    issue_pin(db, user, new)


def issue_pin(db: DbSession, user: User, pin: str | None = None) -> str:
    """Ставит PIN сотруднику. Без аргумента — придумывает свободный.

    PIN уникален в пределах заведения: вход идёт по одному только PIN, и два
    одинаковых означали бы, что смена закрывается от чужого имени.
    """
    others = [
        u
        for u in db.scalars(
            select(User).where(User.venue_id == user.venue_id, User.pin_hash.is_not(None))
        ).all()
        if u.id != user.id
    ]

    def taken(candidate: str) -> bool:
        return any(verify_secret(o.pin_hash, candidate) for o in others)

    need = pin_length(user.role)
    if pin is not None:
        pin = pin.strip()
        if not pin.isdigit() or len(pin) != need:
            raise AuthError(f"PIN — ровно {pin_words(need)}", status=422)
        if taken(pin):
            raise AuthError("Такой PIN уже занят", status=409)
    else:
        for _ in range(200):
            candidate = f"{secrets.randbelow(10 ** need):0{need}d}"
            if not taken(candidate):
                pin = candidate
                break
        else:
            raise AuthError("Не удалось подобрать свободный PIN", status=500)

    user.pin_hash = hash_secret(pin)
    user.pin_failed_attempts = 0
    user.pin_locked_until = None
    return pin
