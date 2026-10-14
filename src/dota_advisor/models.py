from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Role(StrEnum):
    CARRY = "carry"
    MID = "mid"
    OFFLANE = "offlane"
    SOFT_SUPPORT = "soft_support"
    HARD_SUPPORT = "hard_support"


class StateSource(StrEnum):
    MANUAL = "manual"
    SCREENSHOT = "screenshot"
    COMBINED = "combined"


class MatchState(StrictModel):
    hero: str = ""
    role: Role = Role.CARRY
    game_time_seconds: int = Field(default=0, ge=0, le=21600)
    gold: int = Field(default=0, ge=0, le=100000)
    level: int | None = Field(default=None, ge=1, le=30)
    inventory: list[str] = Field(default_factory=list, max_length=20)
    enemy_heroes: list[str] = Field(default_factory=list, max_length=5)
    visible_enemy_items: list[str] = Field(default_factory=list, max_length=30)
    detected_at: datetime = Field(default_factory=utc_now)
    extraction_confidence: Confidence = 1.0
    field_confidence: dict[str, Confidence] = Field(default_factory=dict)
    source: StateSource = StateSource.MANUAL

    @field_validator("hero", "inventory", "enemy_heroes", "visible_enemy_items")
    @classmethod
    def normalize_names(cls, value: str | list[str]) -> str | list[str]:
        if isinstance(value, str):
            return value.strip()
        seen: set[str] = set()
        result: list[str] = []
        for item in value:
            clean = item.strip()
            key = clean.casefold()
            if clean and key not in seen:
                seen.add(key)
                result.append(clean)
        return result


class ManualStateInput(StrictModel):
    hero: str = Field(min_length=1, max_length=80)
    role: Role
    game_time_seconds: int = Field(ge=0, le=21600)
    gold: int = Field(ge=0, le=100000)
    level: int | None = Field(default=None, ge=1, le=30)
    inventory: list[str] = Field(default_factory=list, max_length=20)
    enemy_heroes: list[str] = Field(default_factory=list, max_length=5)

    def to_match_state(self) -> MatchState:
        fields = {
            "hero": 1.0,
            "role": 1.0,
            "game_time_seconds": 1.0,
            "gold": 1.0,
            "level": 1.0,
            "inventory": 1.0,
            "enemy_heroes": 1.0,
        }
        return MatchState(**self.model_dump(), field_confidence=fields)


class VisionObservation(StrictModel):
    game_time_seconds: int | None = Field(default=None, ge=0, le=21600)
    gold: int | None = Field(default=None, ge=0, le=100000)
    level: int | None = Field(default=None, ge=1, le=30)
    inventory: list[str] | None = Field(default=None, max_length=20)
    visible_enemy_items: list[str] = Field(default_factory=list, max_length=30)
    extraction_confidence: Confidence
    field_confidence: dict[str, Confidence]
    warnings: list[str] = Field(default_factory=list, max_length=20)


class ItemComponent(StrictModel):
    name: str
    cost: int = Field(ge=0)


class Item(StrictModel):
    id: str
    name: str
    cost: int = Field(ge=0)
    components: list[ItemComponent] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    roles: list[Role] = Field(default_factory=list)
    hero_synergies: list[str] = Field(default_factory=list)
    counters: list[str] = Field(default_factory=list)
    game_phases: list[Literal["early", "mid", "late"]] = Field(default_factory=list)
    patch_version: str
    data_notice: str
    catalog_category: str = "Curated recommendation"
    purchasable: bool = True
    recommendable: bool = True
    catalog_version: str | None = None
    source_url: str | None = None


class HeroProfile(StrictModel):
    name: str
    typical_roles: list[Role]
    threat_tags: list[str]
    synergy_tags: list[str] = Field(default_factory=list)
    patch_version: str


class StrategyDocument(StrictModel):
    source_id: str
    title: str
    hero: str | None = None
    role: Role | None = None
    patch_version: str
    topic: str
    threat_tags: list[str] = Field(default_factory=list)
    content: str = Field(min_length=20)


class RetrievedPassage(StrategyDocument):
    relevance_score: Confidence = 0.0


class Recommendation(StrictModel):
    item_id: str
    item_name: str
    total_score: Confidence
    score_breakdown: dict[str, float]
    reason: str
    addressed_threats: list[str]
    next_component: str | None = None
    next_component_cost: int | None = Field(default=None, ge=0)
    additional_gold_required: int = Field(ge=0)
    retrieved_sources: list[str]
    generated_at: datetime = Field(default_factory=utc_now)


class AnalysisOutcome(StrictModel):
    state: MatchState
    recommendations: list[Recommendation]
    retrieved_passages: list[RetrievedPassage]
    warnings: list[str] = Field(default_factory=list)
    skipped_unchanged: bool = False
    updated_at: datetime = Field(default_factory=utc_now)


class MonitorInfo(StrictModel):
    index: int
    left: int
    top: int
    width: int
    height: int
    primary: bool = False


class NormalizedRegion(StrictModel):
    x: float = Field(ge=0.0, lt=1.0)
    y: float = Field(ge=0.0, lt=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)

    @field_validator("height")
    @classmethod
    def validate_height(cls, value: float, info: object) -> float:
        return value


class RegionConfiguration(StrictModel):
    layout_id: str
    reference_resolution: tuple[int, int]
    notes: str = ""
    regions: dict[str, NormalizedRegion]

    @field_validator("regions")
    @classmethod
    def validate_region_bounds(
        cls, regions: dict[str, NormalizedRegion]
    ) -> dict[str, NormalizedRegion]:
        required = {"inventory", "gold", "game_time"}
        if missing := required - regions.keys():
            raise ValueError(f"Missing required HUD regions: {', '.join(sorted(missing))}")
        for name, region in regions.items():
            if region.x + region.width > 1.0 or region.y + region.height > 1.0:
                raise ValueError(f"Region '{name}' extends beyond normalized image bounds")
        return regions


class CaptureStartRequest(StrictModel):
    monitor_index: int = Field(default=1, ge=1)
    interval_seconds: float | None = Field(default=None, ge=1.0, le=300.0)


class CaptureStatus(StrictModel):
    running: bool
    monitor_index: int
    interval_seconds: float
    capture_count: int = 0
    analysis_count: int = 0
    skipped_unchanged_count: int = 0
    last_capture_at: datetime | None = None
    last_analysis_at: datetime | None = None
    last_error: str | None = None
    last_analysis_warnings: list[str] = Field(default_factory=list, max_length=20)
    debug_crops: dict[str, str] = Field(default_factory=dict)
