from __future__ import annotations

from dota_advisor.container import build_container
from dota_advisor.models import ManualStateInput, Role


def test_engine_returns_ranked_explainable_recommendations(settings) -> None:
    container = build_container(settings)
    state = ManualStateInput(
        hero="Juggernaut",
        role=Role.CARRY,
        game_time_seconds=1500,
        gold=2200,
        inventory=["Power Treads"],
        enemy_heroes=["Crystal Maiden", "Silencer"],
    ).to_match_state()
    threats = container.advisor.recommendation_engine.infer_threats(state)
    passages = container.strategy_retriever.retrieve(
        hero=state.hero,
        role=state.role.value,
        patch_version=settings.data_version,
        threat_tags=threats,
    )
    recommendations = container.advisor.recommendation_engine.recommend(state, passages)

    assert len(recommendations) == 3
    assert recommendations == sorted(
        recommendations,
        key=lambda recommendation: (
            -recommendation.total_score,
            recommendation.item_name.casefold(),
        ),
    )
    assert all(0 <= recommendation.total_score <= 1 for recommendation in recommendations)
    assert all(
        "threat_coverage" in recommendation.score_breakdown for recommendation in recommendations
    )
    assert any(recommendation.addressed_threats for recommendation in recommendations)
    assert any(recommendation.retrieved_sources for recommendation in recommendations)


def test_duplicate_item_is_penalized(settings) -> None:
    container = build_container(settings)
    state = ManualStateInput(
        hero="Juggernaut",
        role=Role.CARRY,
        game_time_seconds=1800,
        gold=5000,
        inventory=["Black King Bar"],
        enemy_heroes=["Crystal Maiden"],
    ).to_match_state()
    passages = container.strategy_retriever.retrieve(
        hero=state.hero,
        role=state.role.value,
        patch_version=settings.data_version,
        threat_tags=["magical burst"],
    )
    all_recommendations = container.advisor.recommendation_engine.recommend(state, passages)
    assert all(
        recommendation.item_name != "Black King Bar" for recommendation in all_recommendations
    )
