from __future__ import annotations

from collections.abc import Sequence

from .config import RecommendationWeights
from .models import (
    HeroProfile,
    Item,
    ItemComponent,
    MatchState,
    Recommendation,
    RetrievedPassage,
    utc_now,
)
from .protocols import ExplanationService, ItemRepository


class DeterministicExplanationService:
    def explain(
        self,
        item: Item,
        addressed_threats: Sequence[str],
        state: MatchState,
        sources: Sequence[RetrievedPassage],
    ) -> str:
        threat_text = (
            ", ".join(addressed_threats) if addressed_threats else "your current build needs"
        )
        role_text = state.role.value.replace("_", " ")
        source_text = (
            f" This is also supported by {', '.join(source.source_id for source in sources[:2])}."
            if sources
            else ""
        )
        return (
            f"{item.name} gives a {role_text} a practical answer to {threat_text}. "
            f"Its relevant tools are {', '.join(item.tags[:3])}.{source_text}"
        )


class RecommendationEngine:
    def __init__(
        self,
        item_repository: ItemRepository,
        explanation_service: ExplanationService,
        weights: RecommendationWeights,
        result_count: int = 3,
    ) -> None:
        self.item_repository = item_repository
        self.explanation_service = explanation_service
        self.weights = weights
        self.result_count = result_count

    def infer_threats(self, state: MatchState) -> list[str]:
        profiles = {hero.name.casefold(): hero for hero in self.item_repository.list_heroes()}
        threats: list[str] = []
        for enemy in state.enemy_heroes:
            profile = profiles.get(enemy.casefold())
            if profile:
                threats.extend(profile.threat_tags)
        for visible_item in state.visible_enemy_items:
            item = next(
                (
                    candidate
                    for candidate in self.item_repository.list_items()
                    if candidate.name.casefold() == visible_item.casefold()
                ),
                None,
            )
            if item:
                threats.extend(item.tags)
        return list(dict.fromkeys(threats))

    @staticmethod
    def game_phase(game_time_seconds: int) -> str:
        if game_time_seconds < 12 * 60:
            return "early"
        if game_time_seconds < 32 * 60:
            return "mid"
        return "late"

    @staticmethod
    def _next_component(item: Item, state: MatchState) -> tuple[ItemComponent | None, int]:
        owned = {name.casefold() for name in state.inventory}
        components = [
            component for component in item.components if component.name.casefold() not in owned
        ]
        if not components:
            return None, 0
        affordable = [component for component in components if component.cost <= state.gold]
        selected = (
            max(affordable, key=lambda component: component.cost)
            if affordable
            else min(components, key=lambda component: component.cost)
        )
        return selected, max(0, selected.cost - state.gold)

    @staticmethod
    def _hero_profile(state: MatchState, heroes: Sequence[HeroProfile]) -> HeroProfile | None:
        return next(
            (hero for hero in heroes if hero.name.casefold() == state.hero.casefold()), None
        )

    def recommend(
        self,
        state: MatchState,
        passages: Sequence[RetrievedPassage],
    ) -> list[Recommendation]:
        items = [item for item in self.item_repository.list_items() if item.recommendable]
        heroes = self.item_repository.list_heroes()
        profile = self._hero_profile(state, heroes)
        threats = self.infer_threats(state)
        phase = self.game_phase(state.game_time_seconds)
        owned_names = {name.casefold() for name in state.inventory}
        owned_items = [item for item in items if item.name.casefold() in owned_names]
        owned_tags = {tag.casefold() for item in owned_items for tag in item.tags}
        recommendations: list[Recommendation] = []

        for item in items:
            counters = {counter.casefold() for counter in item.counters}
            addressed = [threat for threat in threats if threat.casefold() in counters]
            if "consumable" in {tag.casefold() for tag in item.tags} and not addressed:
                continue
            threat_score = min(1.0, len(addressed) / max(1, min(3, len(threats))))
            hero_score = (
                1.0
                if state.hero.casefold() in {name.casefold() for name in item.hero_synergies}
                else 0.45
            )
            if profile and {tag.casefold() for tag in profile.synergy_tags} & {
                tag.casefold() for tag in item.tags
            }:
                hero_score = max(hero_score, 0.75)
            role_score = 1.0 if state.role in item.roles else 0.1
            phase_score = 1.0 if phase in item.game_phases else 0.2
            affordability_score = min(1.0, state.gold / max(1, item.cost))
            component, additional_gold = self._next_component(item, state)
            component_score = (
                1.0
                if component and component.cost <= state.gold
                else min(1.0, state.gold / max(1, component.cost if component else item.cost))
            )
            supporting = [
                passage
                for passage in passages
                if counters & {tag.casefold() for tag in passage.threat_tags}
            ]
            strategy_score = max((passage.relevance_score for passage in supporting), default=0.0)

            duplicate_penalty = (
                self.weights.duplicate_penalty if item.name.casefold() in owned_names else 0.0
            )
            overlapping_tags = owned_tags & {tag.casefold() for tag in item.tags}
            redundancy_penalty = (
                self.weights.redundancy_penalty
                if owned_items and len(overlapping_tags) >= 2
                else 0.0
            )
            role_penalty = (
                self.weights.inappropriate_role_penalty if state.role not in item.roles else 0.0
            )
            unrealistic = (
                phase == "early" and item.cost > 4000 and state.gold < item.cost * 0.25
            ) or (phase == "mid" and item.cost > 5200 and state.gold < item.cost * 0.15)
            buildup_penalty = self.weights.unrealistic_buildup_penalty if unrealistic else 0.0

            positive = (
                threat_score * self.weights.threat_coverage
                + hero_score * self.weights.hero_synergy
                + role_score * self.weights.role_suitability
                + phase_score * self.weights.game_phase
                + affordability_score * self.weights.affordability
                + component_score * self.weights.component_affordability
                + strategy_score * self.weights.strategy_support
            )
            total = max(
                0.0,
                min(
                    1.0,
                    positive
                    - duplicate_penalty
                    - redundancy_penalty
                    - role_penalty
                    - buildup_penalty,
                ),
            )
            score_breakdown = {
                "threat_coverage": round(threat_score, 4),
                "hero_synergy": round(hero_score, 4),
                "role_suitability": round(role_score, 4),
                "game_phase_suitability": round(phase_score, 4),
                "affordability": round(affordability_score, 4),
                "component_affordability": round(component_score, 4),
                "strategy_support": round(strategy_score, 4),
                "duplicate_penalty": round(duplicate_penalty, 4),
                "redundancy_penalty": round(redundancy_penalty, 4),
                "inappropriate_role_penalty": round(role_penalty, 4),
                "unrealistic_buildup_penalty": round(buildup_penalty, 4),
            }
            recommendations.append(
                Recommendation(
                    item_id=item.id,
                    item_name=item.name,
                    total_score=round(total, 4),
                    score_breakdown=score_breakdown,
                    reason=self.explanation_service.explain(item, addressed, state, supporting),
                    addressed_threats=addressed,
                    next_component=component.name if component else None,
                    next_component_cost=component.cost if component else None,
                    additional_gold_required=additional_gold,
                    retrieved_sources=[source.source_id for source in supporting[:3]],
                    generated_at=utc_now(),
                )
            )
        recommendations.sort(
            key=lambda recommendation: (
                -recommendation.total_score,
                recommendation.item_name.casefold(),
            )
        )
        return recommendations[: self.result_count]
