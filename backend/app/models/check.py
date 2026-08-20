import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamped, UUIDPk

# ------------------------------------------------------------------ чек ---
CHECK_OPEN = "open"
CHECK_CLOSED = "closed"
CHECK_VOID = "void"
CHECK_STATUSES = (CHECK_OPEN, CHECK_CLOSED, CHECK_VOID)

# ------------------------------------------------------------- позиция ----
# Черновик виден только официанту. На станцию позиция попадает, когда
# официант нажал «Отправить», и с этого момента молча она из чека не исчезает.
ITEM_DRAFT = "draft"
ITEM_SENT = "sent"
ITEM_CANCELLED = "cancelled"
ITEM_STATUSES = (ITEM_DRAFT, ITEM_SENT, ITEM_CANCELLED)

# --------------------------------------------------------------- марка ----
TICKET_NEW = "new"
TICKET_ACCEPTED = "accepted"
TICKET_READY = "ready"
TICKET_SERVED = "served"
TICKET_STATUSES = (TICKET_NEW, TICKET_ACCEPTED, TICKET_READY, TICKET_SERVED)

# Единственная разрешённая карта переходов. Всё вне её — ошибка, а не
# «ну почти».
TICKET_TRANSITIONS: dict[str, tuple[str, ...]] = {
    TICKET_NEW: (TICKET_ACCEPTED, TICKET_READY),
    TICKET_ACCEPTED: (TICKET_READY,),
    TICKET_READY: (TICKET_SERVED,),
    TICKET_SERVED: (),
}
TICKET_RANK = {TICKET_NEW: 0, TICKET_ACCEPTED: 1, TICKET_READY: 2, TICKET_SERVED: 3}

# --------------------------------------------------------------- оплата ---
PAY_CARD = "card"
PAY_CASH = "cash"
PAY_METHODS = (PAY_CARD, PAY_CASH)
PAY_NAMES = {PAY_CARD: "Карта", PAY_CASH: "Наличные"}


class Check(UUIDPk, Timestamped, Base):
    """Открытый счёт на столе.

    Живёт, пока за столом сидят: официант доливает в него позиции, отправляет
    их подачами на бар и кухню, а в конце закрывает картой или наличными.
    """

    __tablename__ = "checks"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("venues.id", ondelete="CASCADE"), index=True
    )
    table_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tables.id", ondelete="RESTRICT"), index=True
    )
    waiter_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )

    number: Mapped[int] = mapped_column(Integer, default=0, index=True)
    status: Mapped[str] = mapped_column(String(10), default=CHECK_OPEN, index=True)
    guests: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    comment: Mapped[str | None] = mapped_column(Text, default=None)

    # Скидка в пенсах, ставится на весь чек. Кто и почему — в журнале.
    discount_pence: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    closed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    items: Mapped[list["CheckItem"]] = relationship(
        back_populates="check", cascade="all, delete-orphan"
    )
    orders: Mapped[list["Order"]] = relationship(
        back_populates="check", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="check", cascade="all, delete-orphan"
    )


class Order(UUIDPk, Timestamped, Base):
    """Подача — то, что официант отправил одним нажатием.

    Внутри чека они нумеруются с единицы: «первая подача», «вторая». Станция
    видит не подачу целиком, а свою марку внутри неё.
    """

    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("check_id", "number", name="uq_order_number"),)

    check_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("checks.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer, default=1)
    sent_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    check: Mapped[Check] = relationship(back_populates="orders")
    tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class Ticket(UUIDPk, Timestamped, Base):
    """Одна марка = одна станция внутри одной подачи.

    Бар отдаёт напитки, пока кухня ещё жарит горячее, — и одно другому не
    мешает. Поэтому статус живёт на марке, а не на подаче.
    """

    __tablename__ = "tickets"
    __table_args__ = (UniqueConstraint("order_id", "station", name="uq_ticket_station"),)

    order_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    station: Mapped[str] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(12), default=TICKET_NEW, index=True)

    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    accepted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    ready_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    served_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Официант услышал сигнал «готово» и подтвердил. Пока нет — сигнал
    # повторяется: пропущенное уведомление хуже лишнего.
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    order: Mapped[Order] = relationship(back_populates="tickets")
    items: Mapped[list["CheckItem"]] = relationship(back_populates="ticket")


class CheckItem(UUIDPk, Timestamped, Base):
    """Строка чека.

    Всё, что нужно бармену и кассе, лежит снимком на момент заказа: меню
    завтра поменяют — история не поплывёт.
    """

    __tablename__ = "check_items"

    check_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("checks.id", ondelete="CASCADE"), index=True
    )
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tickets.id", ondelete="SET NULL"), default=None, index=True
    )
    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="SET NULL"), default=None
    )

    status: Mapped[str] = mapped_column(String(12), default=ITEM_DRAFT, index=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)

    unit_price_pence: Mapped[int] = mapped_column(Integer, default=0)
    name_snapshot: Mapped[str] = mapped_column(String(200), default="")
    station_snapshot: Mapped[str] = mapped_column(String(10), default="bar")
    # Что именно выбрали: ["Бутылка", "Absolut", "Микс ×2"]. Это читает
    # бармен на марке, и это не должно поплыть, если завтра переименуют вкус.
    options_snapshot: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    # Ключи выбранного — чтобы повторить позицию одним нажатием.
    options_keys: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    note: Mapped[str | None] = mapped_column(Text, default=None)

    added_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    cancelled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    cancel_reason: Mapped[str | None] = mapped_column(Text, default=None)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    check: Mapped[Check] = relationship(back_populates="items")
    ticket: Mapped[Ticket | None] = relationship(back_populates="items")


class Payment(UUIDPk, Timestamped, Base):
    """Закрытие чека. Карта и наличные — разными строками, потому что
    половину столов в жизни закрывают пополам."""

    __tablename__ = "payments"

    check_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("checks.id", ondelete="CASCADE"), index=True
    )
    method: Mapped[str] = mapped_column(String(10))
    amount_pence: Mapped[int] = mapped_column(Integer, default=0)
    # Сколько дали наличными: сдачу считает касса, а не официант в уме.
    tendered_pence: Mapped[int | None] = mapped_column(Integer, default=None)
    by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    check: Mapped[Check] = relationship(back_populates="payments")
