from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RecommendationWeights(BaseModel):
    threat_coverage: float = 0.27
    hero_synergy: float = 0.14
    role_suitability: float = 0.14
    game_phase: float = 0.10
    affordability: float = 0.12
    component_affordability: float = 0.11
    strategy_support: float = 0.12
    duplicate_penalty: float = 0.75
    redundancy_penalty: float = 0.12
    inappropriate_role_penalty: float = 0.20
    unrealistic_buildup_penalty: float = 0.18


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="DOTA_ADVISOR_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    database_path: Path = Path(".data/advisor.db")
    regions_path: Path = Path("config/hud_regions.json")
    debug_directory: Path = Path(".data/debug-crops")
    debug_save_crops: bool = False

    capture_interval_seconds: float = Field(default=5.0, ge=1.0, le=300.0)
    recommendation_cooldown_seconds: float = Field(default=45.0, ge=0.0, le=3600.0)
    change_threshold: float = Field(default=0.025, gt=0.0, le=1.0)
    confidence_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    monitor_index: int = Field(default=1, ge=1)

    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: float = Field(default=30.0, ge=1.0, le=180.0)
    gemini_max_concurrency: int = Field(default=1, ge=1, le=4)
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")

    data_version: str = "demo-2026.1"
    result_count: int = Field(default=3, ge=2, le=3)
    weights: RecommendationWeights = Field(default_factory=RecommendationWeights)


def ensure_runtime_directories(settings: Settings) -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    if settings.debug_save_crops:
        settings.debug_directory.mkdir(parents=True, exist_ok=True)
