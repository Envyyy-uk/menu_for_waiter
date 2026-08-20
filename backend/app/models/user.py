import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamped, UUIDPk

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_WAITER = "waiter"
ROLE_BAR = "bar"
ROLE_KITCHEN = "kitchen"

# Порядок важен: никто не выдаёт роль выше или равную своей.
ROLE_RANK = {
    ROLE_KITCHEN: 1,
    ROLE_BAR: 1,
    ROLE_WAITER: 1,
    ROLE_MANAGER: 2,
    ROLE_ADMIN: 3,
}
ROLES = (ROLE_ADMIN, ROLE_MANAGER, ROLE_WAITER, ROLE_BAR, ROLE_KITCHEN)

ROLE_NAMES = {
    ROLE_ADMIN: "Администратор",
    ROLE_MANAGER: "Менеджер",
    ROLE_WAITER: "Официант",
    ROLE_BAR: "Бар",
    ROLE_KITCHEN: "Кухня",
}

# Куда отправить человека после ввода PIN.
ROLE_HOME = {
    ROLE_ADMIN: "/admin/",
    ROLE_MANAGER: "/admin/",
    ROLE_WAITER: "/",
    ROLE_BAR: "/station/",
    ROLE_KITCHEN: "/station/",
}


class User(UUIDPk, Timestamped, Base):
    """Сотрудник. Ни почты, ни пароля: вход только по личному PIN.

    PIN — слабый фактор (четыре-шесть цифр), и именно поэтому он блокируется
    после пяти ошибок, а всё, что двигает деньги, пишется в журнал с именем.
    """

    __tablename__ = "users"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("venues.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), default=ROLE_WAITER)

    pin_hash: Mapped[str | None] = mapped_column(String(255), default=None)
    pin_failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    pin_locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # Цвет метки в сетке столов: чей стол, видно без чтения.
    colour: Mapped[str] = mapped_column(String(7), default="#a25a2a", server_default="#a25a2a")

    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Device(UUIDPk, Timestamped, Base):
    """Телефон или планшет. Заводится сам при первом входе — регистрировать
    руками ничего не нужно.

    Нужен ради двух вещей: счётчик неудачных PIN считается на устройстве
    (иначе непонятно, кто именно ошибся), и push уходит на конкретный аппарат.
    """

    __tablename__ = "devices"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("venues.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(120), default="")
    device_token: Mapped[str] = mapped_column(String(64), unique=True)
    user_agent: Mapped[str | None] = mapped_column(Text, default=None)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PushSubscription(UUIDPk, Timestamped, Base):
    """Подписка Web Push. Одна на пару «человек + устройство»: официант
    получает сигнал на свой телефон, а не на все планшеты зала."""

    __tablename__ = "push_subscriptions"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("venues.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
