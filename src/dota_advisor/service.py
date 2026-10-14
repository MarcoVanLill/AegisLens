from __future__ import annotations

import asyncio
import time

from PIL import Image

from .capture import CaptureLoop, CaptureService, ChangeDetector
from .config import Settings
from .models import (
    AnalysisOutcome,
    ManualStateInput,
    MatchState,
    Recommendation,
    RetrievedPassage,
    StateSource,
    VisionObservation,
    utc_now,
)
from .protocols import MatchStateStore, StrategyRetriever, VisionExtractor
from .recommendation import RecommendationEngine


class AdvisorService:
    SCREEN_FIELDS = ("game_time_seconds", "gold", "level", "inventory", "visible_enemy_items")

    def __init__(
        self,
        *,
        settings: Settings,
        capture_service: CaptureService,
        change_detector: ChangeDetector,
        vision_extractor: VisionExtractor,
        strategy_retriever: StrategyRetriever,
        recommendation_engine: RecommendationEngine,
        state_store: MatchStateStore,
    ) -> None:
        self.settings = settings
        self.capture_service = capture_service
        self.change_detector = change_detector
        self.vision_extractor = vision_extractor
        self.strategy_retriever = strategy_retriever
        self.recommendation_engine = recommendation_engine
        self.state_store = state_store
        self._manual_state: MatchState | None = state_store.latest_state()
        self._analysis_lock = asyncio.Lock()
        self._last_recommendation_at = 0.0
        self.capture_loop = CaptureLoop(
            capture_service,
            self.process_image,
            default_monitor=settings.monitor_index,
            default_interval=settings.capture_interval_seconds,
        )

    def set_manual_state(self, request: ManualStateInput) -> MatchState:
        state = request.to_match_state()
        self._manual_state = state
        self.state_store.save_state(state)
        return state

    def current_state(self) -> MatchState | None:
        return self.state_store.latest_state()

    def latest_recommendations(self) -> list[Recommendation]:
        return self.state_store.latest_recommendations()

    def latest_retrieval(self) -> list[RetrievedPassage]:
        return self.state_store.latest_retrieval()

    def _combine(self, observation: VisionObservation) -> tuple[MatchState, list[str]]:
        previous = self.state_store.latest_state()
        manual = self._manual_state or previous or MatchState(extraction_confidence=0.0)
        values = manual.model_dump()
        warnings = list(observation.warnings)
        field_confidence = dict(manual.field_confidence)

        for field in self.SCREEN_FIELDS:
            confidence = observation.field_confidence.get(field, observation.extraction_confidence)
            extracted = getattr(observation, field)
            field_confidence[field] = confidence
            if extracted is not None and confidence >= self.settings.confidence_threshold:
                values[field] = extracted
            else:
                trusted = getattr(previous, field) if previous else getattr(manual, field)
                values[field] = trusted
                warnings.append(
                    f"{field.replace('_', ' ').title()} confidence {confidence:.0%} is below "
                    f"the {self.settings.confidence_threshold:.0%} threshold; the previous "
                    "trusted value was preserved."
                )

        values.update(
            hero=manual.hero,
            role=manual.role,
            enemy_heroes=manual.enemy_heroes,
            detected_at=utc_now(),
            extraction_confidence=observation.extraction_confidence,
            field_confidence=field_confidence,
            source=StateSource.COMBINED,
        )
        return MatchState.model_validate(values), list(dict.fromkeys(warnings))

    def generate_recommendations(
        self, state: MatchState | None = None
    ) -> tuple[list[Recommendation], list[RetrievedPassage]]:
        active = state or self.state_store.latest_state()
        if not active or not active.hero:
            raise ValueError("Set a manual hero and role before requesting recommendations.")
        threats = self.recommendation_engine.infer_threats(active)
        passages = self.strategy_retriever.retrieve(
            hero=active.hero,
            role=active.role.value,
            patch_version=self.settings.data_version,
            threat_tags=threats,
            limit=5,
        )
        recommendations = self.recommendation_engine.recommend(active, passages)
        self.state_store.save_retrieval(passages)
        self.state_store.save_recommendations(recommendations)
        self._last_recommendation_at = time.monotonic()
        return recommendations, passages

    async def process_image(self, image: Image.Image, *, force: bool = False) -> AnalysisOutcome:
        async with self._analysis_lock:
            self.capture_service.assert_visible(image)
            crops = self.capture_service.crop_regions(image)
            if self.settings.debug_save_crops:
                urls = await asyncio.to_thread(self.capture_service.save_debug_crops, crops)
                self.capture_loop.set_debug_crops(urls)

            changed = self.change_detector.has_meaningful_change(crops)
            if not changed and not force:
                state = self.state_store.latest_state() or self._manual_state or MatchState()
                return AnalysisOutcome(
                    state=state,
                    recommendations=self.state_store.latest_recommendations(),
                    retrieved_passages=self.state_store.latest_retrieval(),
                    warnings=[
                        "Relevant HUD regions changed by only "
                        f"{self.change_detector.last_change_score:.2%}; "
                        "expensive extraction was skipped."
                    ],
                    skipped_unchanged=True,
                )

            observation = await self.vision_extractor.extract(crops, self._manual_state)
            state, warnings = self._combine(observation)
            self.state_store.save_state(state)
            recommendations = self.state_store.latest_recommendations()
            passages = self.state_store.latest_retrieval()
            cooldown_elapsed = time.monotonic() - self._last_recommendation_at
            if force or cooldown_elapsed >= self.settings.recommendation_cooldown_seconds:
                recommendations, passages = self.generate_recommendations(state)
            elif recommendations:
                warnings.append(
                    "State updated; recommendations remain inside the configured "
                    f"{self.settings.recommendation_cooldown_seconds:g}s cooldown."
                )
            return AnalysisOutcome(
                state=state,
                recommendations=recommendations,
                retrieved_passages=passages,
                warnings=warnings,
            )

    async def capture_once(self, monitor_index: int, *, force: bool = False) -> AnalysisOutcome:
        image = await asyncio.to_thread(self.capture_service.capture_monitor, monitor_index)
        return await self.process_image(image, force=force)

    async def shutdown(self) -> None:
        await self.capture_loop.stop()
