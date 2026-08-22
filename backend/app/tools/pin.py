"""Сброс входа, когда войти не получается.

Нужен ровно в одном случае: PIN владельца потерян или вход заблокирован
после неудачных попыток, а зайти надо сейчас — например, перед сменой.

    python -m app.tools.pin            # новый PIN владельцу, шесть цифр
    python -m app.tools.pin 246810     # или свой
    python -m app.tools.pin --unlock   # только снять блокировку попыток

Блокировка снимается всегда: после пяти неудач вход ждёт пятнадцать минут, и
человек с новым PIN в руках упирался бы в неё же.
"""

from __future__ import annotations

import sys

from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import AuditLog, User
from app.models.user import ROLE_OWNER
from app.services.auth import ADMIN_PIN_LENGTH, issue_pin


def _unlock(db) -> int:
    """Снять счётчик неудачных попыток. Он ведётся записями журнала."""
    for user in db.scalars(select(User)).all():
        user.pin_failed_attempts = 0
        user.pin_locked_until = None
    result = db.execute(delete(AuditLog).where(AuditLog.action == "pin.failed"))
    return result.rowcount or 0


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--unlock"]
    only_unlock = "--unlock" in sys.argv[1:]

    pin = args[0] if args else None
    if pin is not None and (not pin.isdigit() or len(pin) != ADMIN_PIN_LENGTH):
        print(f"PIN владельца — ровно {ADMIN_PIN_LENGTH} цифр: столько ждёт вход в админку")
        raise SystemExit(2)

    with SessionLocal() as db:
        cleared = _unlock(db)
        if only_unlock:
            db.commit()
            print(f"блокировка снята (записей о неудачах: {cleared})")
            return

        owner = db.scalars(
            select(User).where(User.role == ROLE_OWNER).order_by(User.created_at)
        ).first()
        if owner is None:
            print("владельца в базе нет — заведение ещё не создано")
            raise SystemExit(1)

        issued = issue_pin(db, owner, pin)
        owner.active = True
        db.commit()
        print(f"{owner.name}: новый PIN — {issued}")
        print("Смените его в админке при первом же входе.")


if __name__ == "__main__":
    main()
