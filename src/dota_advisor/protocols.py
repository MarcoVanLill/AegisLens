from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from PIL import Image

from .models import (
    HeroProfile,
    Item,
    MatchState,
    Recommendation,
    RetrievedPassage,
    StrategyDocument,
    VisionObservation,
)


class ItemRepository(Protocol):
    def list_items(self) -> list[Item]: ...

    def get_item(self, item_id: str) -> Item | None: ...

    def list_heroes(self) -> list[HeroProfile]: ...


class StrategyRetriever(Protocol):
    def retrieve(
        self,
        *,
        hero: str | None,
        role: str | None,
        patch_version: str,
        threat_tags: Sequence[str],
        limit: int = 5,
    ) -> list[RetrievedPassage]: ...

    def ingest(self, documents: Sequence[StrategyDocument]) -> int: ...


class VisionExtractor(Protocol):
    async def extract(
        self, crops: dict[str, Image.Image], manual_context: MatchState | None
    ) -> VisionObservation: ...


class ExplanationService(Protocol):
    def explain(
        self,
        item: Item,
        addressed_threats: Sequence[str],
        state: MatchState,
        sources: Sequence[RetrievedPassage],
    ) -> str: ...


class MatchStateStore(Protocol):
    def save_state(self, state: MatchState) -> None: ...

    def latest_state(self) -> MatchState | None: ...

    def save_recommendations(self, recommendations: Sequence[Recommendation]) -> None: ...

    def latest_recommendations(self) -> list[Recommendation]: ...

    def save_retrieval(self, passages: Sequence[RetrievedPassage]) -> None: ...

    def latest_retrieval(self) -> list[RetrievedPassage]: ...
