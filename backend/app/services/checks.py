"""Чеки: открыть стол, набрать заказ, отправить, закрыть.

Три правила держат весь файл:

1. **Черновик станции не виден.** Позиция уходит на бар или кухню только
   после того, как официант нажал «Отправить». До этого он может править её
   как угодно — потом уже нет.
2. **Отправленное молча не исчезает.** Отменить позицию после отправки может
   только менеджер, с причиной, и это видно в журнале. Иначе чек — не
   документ, а черновик, где всё можно переписать задним числом.
3. **Считает сервер.** Браузер присылает, что заказали и сколько, а не сколько
   это стоит.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    CHECK_CLOSED,
    CHECK_OPEN,
    ITEM_CANCELLED,
    ITEM_DRAFT,
    ITEM_SENT,
    PAY_METHODS,
    STATE_OFF,
    STATION_NAMES,
    TICKET_NEW,
    TICKET_RANK,
    TICKET_READY,
    TICKET_SERVED,
    TICKET_TRANSITIONS,
    Check,
    CheckItem,
    MenuItem,
    Order,
    Payment,
    Table,
    Ticket,
    User,
    Venue,
    utcnow,
)
from app.models.menu import STATE_ON, effective_state
from app.services.pricing import PriceError, resolve


class CheckError(Exception):
    def __init__(self, message: str, status: int = 400, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.payload = payload or {}


# --------------------------------------------------------------- деньги ---
def item_total(item: CheckItem) -> int:
    return item.unit_price_pence * item.qty


def live_items(check: Check) -> list[CheckItem]:
    return [i for i in check.items if i.status != ITEM_CANCELLED]


def subtotal(check: Check) -> int:
    return sum(item_total(i) for i in live_items(check))


def total(check: Check) -> int:
    """Скидка не может увести чек в минус — заведение не доплачивает гостю."""
    return max(0, subtotal(check) - (check.discount_pence or 0))


def paid(check: Check) -> int:
    return sum(p.amount_pence for p in check.payments)


def due(check: Check) -> int:
    return max(0, total(check) - paid(check))


# ----------------------------------------------------------------- чеки ---
def open_check(
    db: Session, venue: Venue, table: Table, waiter: User, guests: int = 1, comment: str | None = None
) -> Check:
    if not table.active:
        raise CheckError("Стол выключен", status=409)

    # Номер выдаётся атомарно: два чека, открытые в одну миллисекунду, иначе
    # получат один номер, и в кассе будет два разных чека под одним числом.
    number = db.execute(
        update(Venue)
        .where(Venue.id == venue.id)
        .values(check_seq=Venue.check_seq + 1)
        .returning(Venue.check_seq)
    ).scalar_one()

    check = Check(
        venue_id=venue.id,
        table_id=table.id,
        waiter_id=waiter.id,
        number=number,
        guests=max(1, guests),
        comment=(comment or "").strip() or None,
    )
    db.add(check)
    db.flush()
    return check


def get_check(db: Session, venue: Venue, check_id: uuid.UUID) -> Check:
    check = db.get(Check, check_id)
    if check is None or check.venue_id != venue.id:
        raise CheckError("Чек не найден", status=404)
    return check


def require_open(check: Check) -> Check:
    if check.status != CHECK_OPEN:
        raise CheckError("Чек уже закрыт", status=409)
    return check


# ------------------------------------------------------------- позиции ---
def add_item(
    db: Session,
    check: Check,
    item: MenuItem,
    *,
    qty: int,
    options: dict[str, Any] | None,
    note: str | None,
    user: User,
) -> CheckItem:
    require_open(check)
    if not item.active:
        raise CheckError("Позиции больше нет в меню", status=409)
    state = effective_state(item.state, item.source_state)
    if state != STATE_ON:
        # «Скоро» на сайте — это тоже «сейчас не продаём»: гость видит раздел
        # в меню, но заказать его нельзя, и в зале должно быть так же.
        raise CheckError(
            f"«{item.name}» — {'стоп' if state == STATE_OFF else 'скоро, пока не продаём'}",
            status=409,
        )

    try:
        unit, names, chosen = resolve(item, options)
    except PriceError as exc:
        raise CheckError(exc.message, status=exc.status, payload=exc.payload) from None

    row = CheckItem(
        check_id=check.id,
        menu_item_id=item.id,
        status=ITEM_DRAFT,
        qty=max(1, min(qty, 99)),
        unit_price_pence=unit,
        name_snapshot=item.name,
        station_snapshot=item.station,
        options_snapshot=names,
        options_keys=chosen,
        note=(note or "").strip() or None,
        added_by_id=user.id,
    )
    db.add(row)
    db.flush()
    return row


def get_item(db: Session, check: Check, item_id: uuid.UUID) -> CheckItem:
    row = db.get(CheckItem, item_id)
    if row is None or row.check_id != check.id:
        raise CheckError("Позиция не найдена", status=404)
    return row


def change_draft(db: Session, check: Check, row: CheckItem, *, qty: int | None, note: str | None) -> CheckItem:
    """Править можно только черновик. Отправленное правится отменой и новой
    позицией — так на баре видно, что заказ изменился, а не подменился."""
    require_open(check)
    if row.status != ITEM_DRAFT:
        raise CheckError("Позиция уже отправлена — её можно только отменить", status=409)
    if qty is not None:
        if qty <= 0:
            db.delete(row)
            return row
        row.qty = min(qty, 99)
    if note is not None:
        row.note = note.strip() or None
    return row


def cancel_item(db: Session, check: Check, row: CheckItem, *, user: User, reason: str | None) -> CheckItem:
    require_open(check)
    if row.status == ITEM_CANCELLED:
        return row
    if row.status == ITEM_DRAFT:
        db.delete(row)
        return row
    row.status = ITEM_CANCELLED
    row.cancelled_by_id = user.id
    row.cancelled_at = utcnow()
    row.cancel_reason = (reason or "").strip() or None
    return row


# --------------------------------------------------------------- подача ---
def send(db: Session, check: Check, user: User) -> tuple[Order, list[Ticket]]:
    """Отправить черновик на станции.

    Одно нажатие — одна подача. Внутри неё по марке на станцию: бар отдаёт
    напитки, пока кухня жарит горячее, и одно другому не мешает.
    """
    require_open(check)
    drafts = [i for i in check.items if i.status == ITEM_DRAFT]
    if not drafts:
        raise CheckError("Отправлять нечего", status=409)

    number = max((o.number for o in check.orders), default=0) + 1
    order = Order(check_id=check.id, number=number, sent_by_id=user.id, sent_at=utcnow())
    db.add(order)
    db.flush()

    tickets: dict[str, Ticket] = {}
    for station in sorted({i.station_snapshot for i in drafts}):
        ticket = Ticket(order_id=order.id, station=station, status=TICKET_NEW)
        db.add(ticket)
        db.flush()
        tickets[station] = ticket

    for row in drafts:
        row.status = ITEM_SENT
        row.ticket_id = tickets[row.station_snapshot].id

    return order, list(tickets.values())


def set_ticket_status(db: Session, ticket: Ticket, target: str, user: User | None) -> Ticket:
    """Единственное место, где двигается статус марки.

    Всё вне карты переходов — ошибка, а не «ну почти». Повторное нажатие на
    планшете при этом ничего не ломает: мокрый палец жмёт дважды.

    `user` может быть пустым: планшет станции работает по смене, а не по
    личному входу. Имя тогда не записывается — записывать нечего.
    """
    if target == ticket.status:
        return ticket
    if target not in TICKET_TRANSITIONS.get(ticket.status, ()):
        raise CheckError(f"Переход {ticket.status} → {target} запрещён", status=409)

    now = utcnow()
    ticket.status = target
    who = user.id if user else None
    if target == "accepted":
        ticket.accepted_at = now
        ticket.accepted_by_id = who
    elif target == TICKET_READY:
        ticket.ready_at = now
        ticket.ready_by_id = who
        # Взяли сразу «готово», минуя «принял» — принято тем же нажатием.
        if ticket.accepted_at is None:
            ticket.accepted_at = now
            ticket.accepted_by_id = who
    elif target == TICKET_SERVED:
        ticket.served_at = now
        ticket.acked_at = ticket.acked_at or now
    return ticket


def waiting_tickets(db: Session, venue: Venue, waiter_id) -> list[Ticket]:
    """Готовые марки, которые официант ещё не подтвердил.

    По ним повторяется сигнал: пропущенное уведомление хуже лишнего.
    """
    return list(
        db.scalars(
            select(Ticket)
            .join(Order, Order.id == Ticket.order_id)
            .join(Check, Check.id == Order.check_id)
            .where(
                Check.venue_id == venue.id,
                Check.waiter_id == waiter_id,
                Ticket.status == TICKET_READY,
                Ticket.acked_at.is_(None),
            )
            .order_by(Ticket.ready_at)
        ).all()
    )


# --------------------------------------------------------------- оплата ---
def close_check(
    db: Session, check: Check, parts: list[dict[str, Any]], user: User
) -> Check:
    """Закрыть чек картой, наличными или пополам.

    Сумма частей должна сойтись с итогом ровно. Недобор оставил бы открытый
    долг, который никто не увидит; перебор — это уже чаевые, и они считаются
    отдельно, а не прячутся в сумме чека.
    """
    require_open(check)
    if any(i.status == ITEM_DRAFT for i in check.items):
        raise CheckError("Есть неотправленные позиции", status=409)

    amount_due = due(check)
    # Пустой чек закрывается без оплаты. Стол открыли, гость передумал, всё
    # отменили — брать за это нечего, а стол должен освободиться. Иначе он
    # висит занятым до утра, и официант зовёт менеджера ради нуля.
    if amount_due == 0 and not parts:
        check.status = CHECK_CLOSED
        check.closed_at = utcnow()
        check.closed_by_id = user.id
        return check

    if not live_items(check):
        raise CheckError("В чеке нет позиций", status=409)
    if not parts:
        raise CheckError("Не выбран способ оплаты", status=422)
    given = 0
    for part in parts:
        method = part.get("method")
        if method not in PAY_METHODS:
            raise CheckError("Способ оплаты — только карта или наличные", status=422)
        amount = int(part.get("amount_pence") or 0)
        if amount <= 0:
            raise CheckError("Сумма оплаты должна быть больше нуля", status=422)
        given += amount

    if given != amount_due:
        raise CheckError(
            f"Сумма оплат {given / 100:.2f} не сходится с итогом {amount_due / 100:.2f}",
            status=409,
            payload={"due_pence": amount_due, "given_pence": given},
        )

    for part in parts:
        db.add(
            Payment(
                check_id=check.id,
                method=part["method"],
                amount_pence=int(part["amount_pence"]),
                tendered_pence=part.get("tendered_pence"),
                by_id=user.id,
            )
        )

    check.status = CHECK_CLOSED
    check.closed_at = utcnow()
    check.closed_by_id = user.id
    return check


# ------------------------------------------------------------- ответы -----
def item_payload(row: CheckItem) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name_snapshot,
        "qty": row.qty,
        "unit_price_pence": row.unit_price_pence,
        "total_pence": item_total(row),
        "station": row.station_snapshot,
        "station_name": STATION_NAMES.get(row.station_snapshot, row.station_snapshot),
        "options": list(row.options_snapshot or []),
        "options_keys": dict(row.options_keys or {}),
        "note": row.note,
        "status": row.status,
        "ticket_id": str(row.ticket_id) if row.ticket_id else None,
        "menu_item_id": str(row.menu_item_id) if row.menu_item_id else None,
        "cancel_reason": row.cancel_reason,
    }


def ticket_state(check: Check) -> dict[str, str]:
    """Самая отстающая марка по каждой станции — это и есть состояние стола."""
    out: dict[str, str] = {}
    for order in check.orders:
        for ticket in order.tickets:
            have = out.get(ticket.station)
            if have is None or TICKET_RANK[ticket.status] < TICKET_RANK[have]:
                out[ticket.station] = ticket.status
    return out


def check_payload(check: Check, table_label: str | None = None, waiter_name: str | None = None) -> dict[str, Any]:
    return {
        "id": str(check.id),
        "number": check.number,
        "status": check.status,
        "table": table_label,
        "table_id": str(check.table_id),
        "waiter": waiter_name,
        "waiter_id": str(check.waiter_id) if check.waiter_id else None,
        "guests": check.guests,
        "comment": check.comment,
        "opened_at": check.created_at.isoformat() if check.created_at else None,
        "closed_at": check.closed_at.isoformat() if check.closed_at else None,
        "subtotal_pence": subtotal(check),
        "discount_pence": check.discount_pence or 0,
        "discount_reason": check.discount_reason,
        "total_pence": total(check),
        "paid_pence": paid(check),
        "due_pence": due(check),
        "has_draft": any(i.status == ITEM_DRAFT for i in check.items),
        "stations": ticket_state(check),
        "items": [item_payload(i) for i in sorted(check.items, key=lambda i: i.created_at)],
        "payments": [
            {
                "method": p.method,
                "amount_pence": p.amount_pence,
                "tendered_pence": p.tendered_pence,
            }
            for p in check.payments
        ],
        "orders": [
            {
                "id": str(o.id),
                "number": o.number,
                "sent_at": o.sent_at.isoformat() if o.sent_at else None,
                "tickets": [
                    {"id": str(t.id), "station": t.station, "status": t.status}
                    for t in sorted(o.tickets, key=lambda t: t.station)
                ],
            }
            for o in sorted(check.orders, key=lambda o: o.number)
        ],
    }


def ticket_payload(ticket: Ticket, order: Order, check: Check, table_label: str | None, waiter_name: str | None) -> dict[str, Any]:
    items = [i for i in check.items if i.ticket_id == ticket.id and i.status != ITEM_CANCELLED]
    cancelled = [i for i in check.items if i.ticket_id == ticket.id and i.status == ITEM_CANCELLED]
    return {
        "id": str(ticket.id),
        "station": ticket.station,
        "status": ticket.status,
        "check_id": str(check.id),
        "check_number": check.number,
        "order_number": order.number,
        "table": table_label,
        "waiter": waiter_name,
        "guests": check.guests,
        "comment": check.comment,
        "sent_at": order.sent_at.isoformat() if order.sent_at else None,
        "accepted_at": ticket.accepted_at.isoformat() if ticket.accepted_at else None,
        "ready_at": ticket.ready_at.isoformat() if ticket.ready_at else None,
        "items": [
            {
                "name": i.name_snapshot,
                "qty": i.qty,
                "options": list(i.options_snapshot or []),
                "note": i.note,
            }
            for i in items
        ],
        # Отменённое показывается зачёркнутым, а не пропадает: бармен уже мог
        # начать делать, и об отмене он должен узнать, а не догадаться.
        "cancelled": [
            {"name": i.name_snapshot, "qty": i.qty, "options": list(i.options_snapshot or [])}
            for i in cancelled
        ],
    }
