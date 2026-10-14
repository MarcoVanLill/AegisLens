from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from .models import Item, StrictModel

FANDOM_ITEMS_URL = "https://dota2.fandom.com/wiki/Items"
FANDOM_API_URL = "https://dota2.fandom.com/api.php"
ACTIVE_FILTER = '(game IS NULL OR game="Dota 2 Hidden")'
NON_PURCHASABLE_CATEGORIES = {"Neutral", "Roshan Drop", "Tormentor Reward", "Collectible"}
MINIMUM_EXPECTED_ITEMS = 200


class CatalogEntry(StrictModel):
    name: str
    cost: int = Field(ge=0)
    category: str
    purchasable: bool
    page: str


class CatalogSnapshot(StrictModel):
    version: str
    retrieved_at: str
    source_url: str
    source_api: str
    source_query: str
    item_count: int = Field(ge=MINIMUM_EXPECTED_ITEMS)
    items: list[CatalogEntry]


def bundled_catalog_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "item_catalog.json"


def load_catalog_snapshot(path: Path | None = None) -> CatalogSnapshot:
    snapshot_path = path or bundled_catalog_path()
    snapshot = CatalogSnapshot.model_validate_json(snapshot_path.read_text(encoding="utf-8"))
    if snapshot.item_count != len(snapshot.items):
        raise ValueError(
            f"Catalog metadata says {snapshot.item_count} items but contains {len(snapshot.items)}."
        )
    names = [entry.name.casefold() for entry in snapshot.items]
    if len(names) != len(set(names)):
        raise ValueError("Catalog snapshot contains duplicate item names.")
    return snapshot


def _item_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")


def _source_url(page: str) -> str:
    page_name = urllib.parse.quote(page.replace(" ", "_"), safe="()'-")
    return f"https://dota2.fandom.com/wiki/{page_name}"


def build_item_catalog(curated_items: list[Item]) -> list[Item]:
    snapshot = load_catalog_snapshot()
    curated_by_name = {item.name.casefold(): item for item in curated_items}
    catalog: list[Item] = []
    for entry in snapshot.items:
        curated = curated_by_name.get(entry.name.casefold())
        common = {
            "cost": entry.cost if entry.cost > 0 else (curated.cost if curated else 0),
            "catalog_category": entry.category,
            "purchasable": entry.purchasable,
            "catalog_version": snapshot.version,
            "source_url": _source_url(entry.page),
        }
        if curated:
            catalog.append(curated.model_copy(update=common))
            continue
        catalog.append(
            Item(
                id=_item_id(entry.name),
                name=entry.name,
                components=[],
                tags=[],
                roles=[],
                hero_synergies=[],
                counters=[],
                game_phases=[],
                patch_version=snapshot.version,
                data_notice=(
                    "Inventory-recognition catalog entry from a dated Fandom Cargo snapshot. "
                    "It is not curated recommendation metadata or a live-patch guarantee."
                ),
                recommendable=False,
                **common,
            )
        )
    return catalog


class FandomCatalogClient:
    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(self) -> CatalogSnapshot:
        parameters = urllib.parse.urlencode(
            {
                "action": "cargoquery",
                "format": "json",
                "origin": "*",
                "tables": "items",
                "fields": "_pageName=page,title,item_cost,type,game",
                "where": ACTIVE_FILTER,
                "limit": "500",
            }
        )
        request = urllib.request.Request(
            f"{FANDOM_API_URL}?{parameters}",
            headers={"User-Agent": "AegisLens/0.1 local item catalog updater"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        entries = []
        for result in payload.get("cargoquery", []):
            row = result.get("title", {})
            name = str(row.get("title") or "").strip()
            if not name:
                continue
            raw_cost = str(row.get("item cost") or "")
            category = str(row.get("type") or "Uncategorized")
            entries.append(
                CatalogEntry(
                    name=name,
                    cost=int(raw_cost) if raw_cost.isdigit() else 0,
                    category=category,
                    purchasable=category not in NON_PURCHASABLE_CATEGORIES,
                    page=str(row.get("page") or name),
                )
            )
        entries.sort(key=lambda entry: entry.name.casefold())
        unique = {entry.name.casefold(): entry for entry in entries}
        if len(unique) < MINIMUM_EXPECTED_ITEMS:
            raise RuntimeError(
                f"Fandom returned only {len(unique)} unique active item records; refusing to "
                "replace the known-good snapshot."
            )
        retrieved_at = datetime.now(UTC).date().isoformat()
        return CatalogSnapshot(
            version=f"fandom-active-snapshot-{retrieved_at}",
            retrieved_at=retrieved_at,
            source_url=FANDOM_ITEMS_URL,
            source_api=f"{FANDOM_API_URL}?action=cargoquery",
            source_query="items where game is null or Dota 2 Hidden",
            item_count=len(unique),
            items=list(unique.values()),
        )

    def refresh_bundled_snapshot(self) -> CatalogSnapshot:
        snapshot = self.fetch()
        path = bundled_catalog_path()
        temporary_path = path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps(snapshot.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
        return snapshot
