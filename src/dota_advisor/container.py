from __future__ import annotations

from dataclasses import dataclass

from .capture import CaptureService, ChangeDetector
from .config import Settings, ensure_runtime_directories
from .protocols import VisionExtractor
from .recommendation import DeterministicExplanationService, RecommendationEngine
from .repository import (
    Database,
    SQLiteItemRepository,
    SQLiteMatchStateStore,
    SQLiteStrategyRetriever,
)
from .seeds import DEMO_HEROES, DEMO_ITEMS, DEMO_STRATEGIES
from .service import AdvisorService
from .vision import FallbackVisionExtractor, GeminiVisionExtractor, LocalVisionExtractor


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    database: Database
    item_repository: SQLiteItemRepository
    strategy_retriever: SQLiteStrategyRetriever
    state_store: SQLiteMatchStateStore
    capture_service: CaptureService
    advisor: AdvisorService


def build_container(
    settings: Settings | None = None,
    *,
    vision_extractor: VisionExtractor | None = None,
) -> AppContainer:
    active_settings = settings or Settings()
    ensure_runtime_directories(active_settings)
    database = Database(active_settings.database_path)
    database.initialize()
    item_repository = SQLiteItemRepository(database)
    item_repository.seed(DEMO_ITEMS, DEMO_HEROES)
    strategy_retriever = SQLiteStrategyRetriever(database)
    strategy_retriever.ingest(DEMO_STRATEGIES)
    state_store = SQLiteMatchStateStore(database)
    capture_service = CaptureService(
        active_settings.regions_path,
        active_settings.debug_directory,
    )
    if vision_extractor is None:
        local = LocalVisionExtractor()
        if active_settings.gemini_api_key:
            gemini = GeminiVisionExtractor(
                api_key=active_settings.gemini_api_key,
                model=active_settings.gemini_model,
                timeout_seconds=active_settings.gemini_timeout_seconds,
                max_concurrency=active_settings.gemini_max_concurrency,
            )
            vision_extractor = FallbackVisionExtractor(gemini, local)
        else:
            vision_extractor = local
    recommendation_engine = RecommendationEngine(
        item_repository,
        DeterministicExplanationService(),
        active_settings.weights,
        active_settings.result_count,
    )
    advisor = AdvisorService(
        settings=active_settings,
        capture_service=capture_service,
        change_detector=ChangeDetector(active_settings.change_threshold),
        vision_extractor=vision_extractor,
        strategy_retriever=strategy_retriever,
        recommendation_engine=recommendation_engine,
        state_store=state_store,
    )
    return AppContainer(
        settings=active_settings,
        database=database,
        item_repository=item_repository,
        strategy_retriever=strategy_retriever,
        state_store=state_store,
        capture_service=capture_service,
        advisor=advisor,
    )
