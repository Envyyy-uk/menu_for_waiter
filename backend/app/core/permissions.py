"""Матрица прав: одно место, где записано, кто что может.

Эндпойнты ссылаются сюда и никогда не сравнивают роль строкой — иначе через
полгода «менеджер» в трёх местах будет означать три разные вещи.

Спрятанная кнопка защитой не является: проверка здесь и на каждом эндпойнте.

Шесть ролей, и каждая отвечает за своё:

* **владелец** — деньги и доступы, включая склад. Единственный, кого нельзя
  выключить чужими руками;
* **администратор** — заводит людей, столы и меню, смотрит отчёты и склад;
* **менеджер** — работает в зале и разбирает спорное: скидки, отмены,
  забытый PIN. К складу не допущен;
* **бармен** — пробивает сам за стойкой и видит марки своей станции;
* **официант** — зал и чеки;
* **кухня** — только марки.
"""

from app.models.user import (
    ROLE_ADMIN,
    ROLE_BAR,
    ROLE_KITCHEN,
    ROLE_MANAGER,
    ROLE_OWNER,
    ROLE_RANK,
    ROLE_WAITER,
)

ALL = (ROLE_OWNER, ROLE_ADMIN, ROLE_MANAGER, ROLE_BAR, ROLE_WAITER, ROLE_KITCHEN)
# Кто работает с чеками. Бармен здесь намеренно: за стойкой сидят гости, и
# заказ у них принимает он, а не бегает искать официанта.
FLOOR = (ROLE_OWNER, ROLE_ADMIN, ROLE_MANAGER, ROLE_BAR, ROLE_WAITER)
STATION = (ROLE_OWNER, ROLE_ADMIN, ROLE_MANAGER, ROLE_BAR, ROLE_KITCHEN)
MANAGERS = (ROLE_OWNER, ROLE_ADMIN, ROLE_MANAGER)
ADMINS = (ROLE_OWNER, ROLE_ADMIN)
OWNER_ONLY = (ROLE_OWNER,)

PERMISSIONS: dict[str, tuple[str, ...]] = {
    # Зал: столы и чеки
    "checks.view": FLOOR,
    "checks.edit": FLOOR,      # открыть чек, добавить позицию, отправить
    "checks.close": FLOOR,     # закрыть картой или наличными
    "checks.discount": MANAGERS,   # скидка — только с менеджером
    "checks.void": MANAGERS,       # отменить отправленную позицию или весь чек
    "checks.transfer": MANAGERS,   # передать стол другому официанту
    # Станции
    "tickets.view": STATION,
    "tickets.status": STATION,
    # Стоп-лист — его ставит и бар, и кухня: кончилось у них, а не у менеджера
    "items.state": ALL,
    # Меню и зал
    "items.edit": ADMINS,
    "tables.manage": ADMINS,
    # Склад — это деньги на полке, и правит его тот, кто за них отвечает.
    "stock.view": ADMINS,
    "stock.edit": ADMINS,
    # Свою смену открывает и закрывает каждый, кто выходит в зал: табель
    # ведёт сам человек, а не тот, кто вспомнит о нём в конце месяца.
    "work.shift": FLOOR,
    # Табель на всех — деньги: по нему считают зарплату.
    "timesheet.view": MANAGERS,
    # Отчёты и доступы
    "reports": MANAGERS,
    # Список оплат — то же самое право, что и отчёт: менеджер на смене
    # разбирает спорный чек сам, не дожидаясь администратора.
    "payments.view": MANAGERS,
    # Список сотрудников менеджеру нужен ради одного: сбросить забытый PIN.
    # Заводить людей и менять роли он при этом не может.
    "users.view": MANAGERS,
    "users.manage": ADMINS,    # заводить людей, менять роли, выключать
    # Сброс чужого PIN — отдельное право: это доступ к деньгам, и делается он
    # по просьбе или когда PIN забыли. Менеджер на смене должен уметь это сам,
    # иначе официант стоит без входа до приезда администратора.
    "users.pin": MANAGERS,
    "stations.manage": ADMINS,     # PIN планшета станции
    "shifts.view": MANAGERS,
    "audit.view": MANAGERS,
    "venue.manage": OWNER_ONLY,
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


def can_touch_user(actor_role: str, target_role: str) -> bool:
    """Можно ли трогать этого человека: менять ему роль, PIN, выключать.

    Никто не трогает того, кто выше. Иначе менеджер сбрасывает PIN владельцу
    и заходит вместо него — а это уже не забытый PIN, а смена собственника.
    """
    return ROLE_RANK.get(actor_role, 0) >= ROLE_RANK.get(target_role, 99)
