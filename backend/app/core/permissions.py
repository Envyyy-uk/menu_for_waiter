"""Матрица прав: одно место, где записано, кто что может.

Эндпойнты ссылаются сюда и никогда не сравнивают роль строкой — иначе через
полгода «менеджер» в трёх местах будет означать три разные вещи.

Спрятанная кнопка защитой не является: проверка здесь и на каждом эндпойнте.
"""

from app.models.user import (
    ROLE_ADMIN,
    ROLE_BAR,
    ROLE_KITCHEN,
    ROLE_MANAGER,
    ROLE_RANK,
    ROLE_WAITER,
)

ALL = (ROLE_ADMIN, ROLE_MANAGER, ROLE_WAITER, ROLE_BAR, ROLE_KITCHEN)
FLOOR = (ROLE_ADMIN, ROLE_MANAGER, ROLE_WAITER)
STATION = (ROLE_ADMIN, ROLE_MANAGER, ROLE_BAR, ROLE_KITCHEN)
MANAGERS = (ROLE_ADMIN, ROLE_MANAGER)
ADMIN_ONLY = (ROLE_ADMIN,)

PERMISSIONS: dict[str, tuple[str, ...]] = {
    # Зал: столы и чеки
    "checks.view": FLOOR,
    "checks.edit": FLOOR,  # открыть чек, добавить позицию, отправить
    "checks.close": FLOOR,  # закрыть картой или наличными
    "checks.discount": MANAGERS,  # скидка — только с менеджером
    "checks.void": MANAGERS,  # отменить отправленную позицию или весь чек
    "checks.transfer": MANAGERS,  # передать стол другому официанту
    # Станции
    "tickets.view": STATION,
    "tickets.status": STATION,
    # Стоп-лист — его ставит и бар, и кухня: кончилось у них, а не у менеджера
    "items.state": ALL,
    # Меню и зал
    "items.edit": MANAGERS,
    "tables.manage": MANAGERS,
    # Отчёты и доступы
    "reports": MANAGERS,
    "users.manage": ADMIN_ONLY,
    "audit.view": MANAGERS,
}


def can(role: str, permission: str) -> bool:
    allowed = PERMISSIONS.get(permission)
    if allowed is None:
        # Неизвестное право — не «можно по умолчанию». Опечатка в названии не
        # должна открывать эндпойнт всем.
        return False
    return role in allowed


def can_assign_role(actor_role: str, target_role: str) -> bool:
    """Роль выше своей не выдаёт никто.

    Равную — можно: второго администратора заводит администратор, и это
    намеренно. Заведение с единственным админом умирает вместе с его PIN.
    """
    if not can(actor_role, "users.manage"):
        return False
    return ROLE_RANK.get(target_role, 99) <= ROLE_RANK.get(actor_role, 0)
