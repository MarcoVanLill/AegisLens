from __future__ import annotations

from dota_advisor.catalog import load_catalog_snapshot
from dota_advisor.container import build_container


def test_bundled_catalog_contains_all_fandom_active_records() -> None:
    snapshot = load_catalog_snapshot()
    names = {entry.name for entry in snapshot.items}

    assert snapshot.version == "fandom-active-snapshot-2026-10-14"
    assert snapshot.item_count == 276
    assert len(names) == 276
    assert {"Iron Branch", "Black King Bar", "Aegis of the Immortal", "Apex"} <= names


def test_catalog_separates_recognition_from_recommendation(settings) -> None:
    container = build_container(settings)
    items = container.item_repository.list_items()
    by_name = {item.name: item for item in items}

    assert len(items) == 276
    assert sum(item.recommendable for item in items) == 22
    assert by_name["Black King Bar"].recommendable
    assert by_name["Iron Branch"].purchasable
    assert not by_name["Iron Branch"].recommendable
    assert not by_name["Aegis of the Immortal"].purchasable
    assert not by_name["Aegis of the Immortal"].recommendable
