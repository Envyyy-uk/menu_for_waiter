import pytest
from sqlalchemy import select

from app.models import MenuItem
from app.services.pricing import PriceError, resolve


def item(db, key: str) -> MenuItem:
    return db.scalars(select(MenuItem).where(MenuItem.key == key)).one()


def test_size_replaces_price(db, venue):
    vodka = item(db, "vodka-house")
    price, names, _ = resolve(vodka, {"size": "bottle", "kind": "absolut"})
    assert price == 23000
    assert names == ["Бутылка", "Absolut"]


def test_required_group_cannot_be_skipped(db, venue):
    """«Мохито» без вкуса — это не заказ, а загадка для бармена."""
    vodka = item(db, "vodka-house")
    with pytest.raises(PriceError) as exc:
        resolve(vodka, {"size": "ml50"})
    assert exc.value.payload["missing_option"] == "kind"


def test_addon_adds_and_counts(db, venue):
    vodka = item(db, "vodka-house")
    price, names, chosen = resolve(
        vodka, {"size": "ml50", "kind": "stoli", "mixer": ["mixer", "mixer"]}
    )
    assert price == 1300 + 300 * 2
    assert "Микс ×2" in names
    assert chosen["mixer"] == ["mixer", "mixer"]


def test_addon_respects_limit(db, venue):
    vodka = item(db, "vodka-house")
    with pytest.raises(PriceError):
        resolve(vodka, {"size": "ml50", "kind": "stoli", "mixer": ["mixer"] * 7})


def test_dependent_group_required_only_when_relevant(db, venue):
    """Марку дарк-лифа не спрашивают у того, кто взял сигарный лист."""
    hookah = item(db, "hookah")
    price, names, chosen = resolve(hookah, {"leaf": "cigar-leaf", "cigar-leaf": "kraken"})
    assert price == 5000
    assert names == ["Сигарный лист", "Kraken"]
    assert "dark-leaf" not in chosen

    with pytest.raises(PriceError):
        resolve(hookah, {"leaf": "dark-leaf"})


def test_group_add_pence_applies_once(db, venue):
    hookah = item(db, "hookah")
    price, names, _ = resolve(
        hookah, {"leaf": "dark-leaf", "dark-leaf": "darkside", "fruit-head": "apple"}
    )
    assert price == 5000 + 1000
    assert "Яблоко" in names


def test_stale_choice_from_hidden_group_is_dropped(db, venue):
    """Выбор из выключённой группы не должен попасть в цену."""
    hookah = item(db, "hookah")
    price, _, chosen = resolve(
        hookah,
        {"leaf": "cigar-leaf", "cigar-leaf": "satyr", "dark-leaf": "tangiers"},
    )
    assert price == 5000
    assert "dark-leaf" not in chosen


def test_unknown_group_is_rejected(db, venue):
    with pytest.raises(PriceError):
        resolve(item(db, "mojito"), {"nonsense": "x"})
