"""Меню приезжает с сайта само — и не ломает смену, когда сайт лежит."""

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import MenuItem
from app.models.menu import effective_state
from app.services import menu_sync
from app.services.catalogue import CatalogueError, convert
from app.services.menu_sync import SyncError, apply
from tests.test_floor import add, hall, login, open_check  # noqa: F401

CATALOGUE = {
    "venue": {"key": "podval", "name": "Меню", "currency": "GBP"},
    "categories": [{"key": "bar", "names": {"ru": "Бар", "en": "Bar"}}],
    "addons": {"mixer": {"price_pence": 300, "names": {"ru": "Микс"}}},
    "items": [
        {
            "key": "soft-drink",
            "name": "Soft Drinks / Juices",
            "category": "beer-soft",
            "station": "bar",
            "price_pence": 500,
            "desc": {"ru": "Газированные напитки и соки"},
            "options": [
                {
                    "key": "kind",
                    "label": "opt.kind",
                    "choices": [{"key": "cola", "name": "Cola"}, {"key": "fanta", "name": "Fanta"}],
                }
            ],
        },
        {
            "key": "mojito",
            "name": "Mojito",
            "category": "bar",
            "station": "bar",
            "price_pence": 1600,
            "desc": {"ru": "Ром, сахар, лайм, мята"},
            "alt": ["мохито"],
        },
        {
            "key": "new-thing",
            "name": "Espresso Martini",
            "category": "bar",
            "station": "bar",
            "price_pence": 1400,
            "desc": {"ru": "Водка, кофе, ликёр"},
        },
    ],
}


def catalogue(**changes):
    body = json.loads(json.dumps(CATALOGUE))
    body.update(changes)
    return body


def keys(db, venue):
    return {
        i.key: i
        for i in db.scalars(select(MenuItem).where(MenuItem.venue_id == venue.id)).all()
    }


# ------------------------------------------------------------ разбор ------
def test_real_catalogue_converts(db, venue):
    """Тот самый файл с сайта — на нём и проверяем, а не на выдуманном."""
    src = Path(__file__).resolve().parents[2] / "seed_menu.json"
    snapshot = json.loads(src.read_text(encoding="utf-8"))
    assert len(snapshot["items"]) == 63

    hookah = next(i for i in snapshot["items"] if i["key"] == "hookah")
    leaf = next(g for g in hookah["options"] if g["key"] == "dark-leaf")
    # Зависимая группа и добавки переживают преобразование — на них держится
    # половина цен в баре.
    assert leaf["depends"] == {"group": "leaf", "value": "dark-leaf"}
    vodka = next(i for i in snapshot["items"] if i["key"] == "absolut")
    mixer = next(g for g in vodka["options"] if g["key"] == "mixer")
    assert mixer["mode"] == "many"
    assert mixer["choices"][0]["add_pence"] == 300
    # Миксы собираются из самого каталога: добавили на сайте сок — он
    # появился и здесь, руками ничего дописывать не нужно.
    assert {c["name"] for c in mixer["choices"]} >= {"Cola", "Sprite", "Red Bull"}


def test_empty_catalogue_is_refused():
    """Пустой каталог почти наверняка страница ошибки, а не заведение без меню."""
    with pytest.raises(CatalogueError):
        convert({"items": []})
    with pytest.raises(CatalogueError):
        convert({"nonsense": True})


def test_items_without_a_name_are_skipped():
    payload = convert(catalogue(items=CATALOGUE["items"] + [{"key": "broken"}]))
    assert [i["key"] for i in payload["items"]] == ["soft-drink", "mojito", "new-thing"]


# ------------------------------------------------------------- запись -----
def test_new_item_appears_and_missing_one_hides(db, venue):
    report = apply(db, venue, convert(catalogue()))
    db.commit()

    have = keys(db, venue)
    assert have["new-thing"].name == "Espresso Martini"
    assert "Espresso Martini" in report["added"]

    # Всё, чего в каталоге нет, перестаёт показываться — но остаётся в базе:
    # на эти позиции ссылаются закрытые чеки.
    assert have["hookah"].active is False
    assert "Hookah" in report["removed"]
    assert db.get(MenuItem, have["hookah"].id) is not None


def test_returned_item_reads_as_added(db, venue):
    """Убрали с сайта и вернули — для человека позиция именно появилась."""
    apply(db, venue, convert(catalogue()))
    db.commit()

    without = catalogue()
    without["items"] = [i for i in without["items"] if i["key"] != "new-thing"]
    gone = apply(db, venue, convert(without))
    db.commit()
    assert "Espresso Martini" in gone["removed"]

    back = apply(db, venue, convert(catalogue()))
    db.commit()
    assert "Espresso Martini" in back["added"]
    assert "Espresso Martini" not in back["updated"]


def test_stop_list_survives_sync(db, venue):
    """Кончилось час назад — синхронизация не возвращает это в продажу."""
    item = keys(db, venue)["mojito"]
    item.state = "off"
    db.commit()

    apply(db, venue, convert(catalogue()))
    db.commit()
    assert keys(db, venue)["mojito"].state == "off"


def test_price_change_is_written_down(db, venue):
    """Цена — это деньги, и неважно, поменял её человек или сайт."""
    from app.models import AuditLog

    changed = catalogue()
    next(i for i in changed["items"] if i["key"] == "mojito")["price_pence"] = 1900
    report = apply(db, venue, convert(changed))
    db.commit()

    assert report["prices"] == [{"name": "Mojito", "before": 1600, "after": 1900}]
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "item.price_sync")).one()
    assert entry.before["price_pence"] == 1600
    assert entry.after["price_pence"] == 1900


def test_unchanged_catalogue_reports_nothing(db, venue):
    apply(db, venue, convert(catalogue()))
    db.commit()
    again = apply(db, venue, convert(catalogue()))
    db.commit()
    assert again["added"] == []
    assert again["updated"] == []
    assert again["removed"] == []


def test_empty_payload_never_wipes_the_menu(db, venue):
    before = len(keys(db, venue))
    with pytest.raises(SyncError):
        apply(db, venue, {"items": []})
    db.rollback()
    assert len(keys(db, venue)) == before


# --------------------------------------------------------- сайт лежит -----
def test_dead_site_leaves_the_menu_alone(db, venue, monkeypatch):
    """Работающее старое меню лучше пустого нового."""
    monkeypatch.setattr(
        menu_sync.settings, "menu_source_url", "http://127.0.0.1:9/menu.json"
    )
    monkeypatch.setattr(menu_sync.settings, "menu_labels_url", "")
    before = len(keys(db, venue))

    result = menu_sync.sync_once(db, venue)
    assert result["status"] == "error"
    assert len(keys(db, venue)) == before
    # И об этом видно в админке, а не только в логах.
    assert venue.menu_sync["status"] == "error"
    assert venue.menu_sync["error"]


def test_garbage_instead_of_catalogue_is_refused(db, venue, monkeypatch):
    monkeypatch.setattr(menu_sync.settings, "menu_source_url", "https://example.invalid/menu.json")
    monkeypatch.setattr(menu_sync.settings, "menu_labels_url", "")
    monkeypatch.setattr(menu_sync, "fetch", lambda url, etag=None: ({"oops": 1}, "e1"))

    before = len(keys(db, venue))
    result = menu_sync.sync_once(db, venue)
    assert result["status"] == "error"
    assert len(keys(db, venue)) == before


def test_unchanged_site_is_not_refetched(db, venue, monkeypatch):
    """Метка версии экономит не трафик, а журнал: без неё каждая проверка
    выглядела бы изменением меню."""
    monkeypatch.setattr(menu_sync.settings, "menu_source_url", "https://example.invalid/menu.json")
    monkeypatch.setattr(menu_sync.settings, "menu_labels_url", "")

    seen = []

    def fake_fetch(url, etag=None):
        seen.append(etag)
        if etag == "v1":
            return None, etag
        return catalogue(), "v1"

    monkeypatch.setattr(menu_sync, "fetch", fake_fetch)

    assert menu_sync.sync_once(db, venue)["status"] == "ok"
    assert menu_sync.sync_once(db, venue)["status"] == "unchanged"
    assert seen == [None, "v1"]


def test_sync_is_off_without_a_url(db, venue, monkeypatch):
    monkeypatch.setattr(menu_sync.settings, "menu_source_url", "")
    assert menu_sync.sync_once(db, venue) == {"status": "off"}


# ------------------------------------------------------------ по API ------
def test_admin_can_pull_the_menu_now(client, hall, monkeypatch):
    monkeypatch.setattr(menu_sync.settings, "menu_source_url", "https://example.invalid/menu.json")
    monkeypatch.setattr(menu_sync.settings, "menu_labels_url", "")
    monkeypatch.setattr(menu_sync, "fetch", lambda url, etag=None: (catalogue(), "v1"))

    login(client, "1111")
    assert client.post("/api/admin/menu/sync").status_code == 403
    login(client, "444444")   # менеджер меню не правит — это цены
    assert client.post("/api/admin/menu/sync").status_code == 403

    login(client, "123456")
    body = client.post("/api/admin/menu/sync").json()
    assert body["status"] == "ok"
    assert "Espresso Martini" in body["report"]["added"]

    # И официант видит новинку сразу, без перезапуска.
    login(client, "1111")
    names = [i["name"] for i in client.get("/api/menu").json()["items"]]
    assert "Espresso Martini" in names


def test_sync_status_is_visible(client, hall):
    login(client, "123456")
    state = client.get("/api/admin/menu/sync").json()
    assert "enabled" in state
    assert "every_minutes" in state


# ------------------------------------------------- стоп приезжает с сайта --
def test_hidden_on_the_site_is_stop_in_the_hall(db, venue):
    """На сайте позицию скрыли — в зале её продавать нельзя.

    Это ровно то, ради чего каталог один: официант не должен узнавать о
    скрытой позиции от гостя.
    """
    payload = catalogue()
    payload["items"][0]["state"] = "off"
    menu_sync.apply(db, venue, payload)
    db.commit()

    item = keys(db, venue)[payload["items"][0]["key"]]
    assert item.source_state == "off"
    assert effective_state(item.state, item.source_state) == "off"


def test_soon_section_is_not_orderable(db, venue):
    """Раздел, помеченный на сайте «скоро», гость видит, а заказать не может."""
    payload = catalogue()
    payload["items"][0]["state"] = "soon"
    menu_sync.apply(db, venue, payload)
    db.commit()

    item = keys(db, venue)[payload["items"][0]["key"]]
    assert effective_state(item.state, item.source_state) == "soon"


def test_site_does_not_clear_the_bar_stop(db, venue):
    """Два выключателя, и каталог не трогает чужой.

    Иначе проверка меню снимает стоп, который бармен поставил десять минут
    назад, — и позиция уходит гостю, хотя её нет.
    """
    payload = catalogue()
    menu_sync.apply(db, venue, payload)
    db.commit()

    item = keys(db, venue)[payload["items"][0]["key"]]
    item.state = "off"          # бар: кончилось прямо сейчас
    db.commit()

    menu_sync.apply(db, venue, payload)   # сайт говорит «продаём»
    db.commit()
    db.expire_all()
    item = keys(db, venue)[payload["items"][0]["key"]]
    assert item.state == "off"
    assert item.source_state == "on"
    assert effective_state(item.state, item.source_state) == "off"


def test_a_whole_section_goes_on_stop(client, hall):
    """Кончился газ — встали все кальяны, а не один."""
    login(client, "2222")     # бармен: стоп ставит тот, у кого кончилось
    menu = client.get("/api/menu").json()
    category = next(c["key"] for c in menu["categories"] if c["key"])
    mine = [i for i in menu["items"] if i["category"] == category]
    assert len(mine) > 1

    r = client.post("/api/menu/category/state", json={"category": category, "state": "off"})
    assert r.status_code == 200, r.text
    assert r.json()["count"] == len(mine)

    after = client.get("/api/menu").json()["items"]
    assert all(i["state"] == "off" for i in after if i["category"] == category)

    # И снимается так же, одним нажатием.
    client.post("/api/menu/category/state", json={"category": category, "state": "on"})
    back = client.get("/api/menu").json()["items"]
    assert all(i["state"] == "on" for i in back if i["category"] == category)


def test_unknown_section_is_not_a_stop(client, hall):
    login(client, "2222")
    assert client.post(
        "/api/menu/category/state", json={"category": "нет-такого", "state": "off"}
    ).status_code == 404
