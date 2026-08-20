"""Журнал действий: кто, что и когда.

Пишется на каждом действии, которое двигает деньги, доступ или наличие:
закрытие чека, скидка, отмена позиции, выдача PIN. Формат один: что сделали,
с чем, как было, как стало.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog


class _Record:
    def write(
        self,
        db: Session,
        *,
        venue_id,
        user_id,
        action: str,
        entity: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> AuditLog:
        row = AuditLog(
            venue_id=venue_id,
            user_id=user_id,
            action=action,
            entity=entity,
            before=before,
            after=after,
        )
        db.add(row)
        return row

    def count_recent(
        self, db: Session, venue_id, *, action: str, entity: str, since: datetime
    ) -> int:
        return db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.venue_id == venue_id,
                AuditLog.action == action,
                AuditLog.entity == entity,
                AuditLog.at >= since,
            )
        ) or 0


record = _Record()
