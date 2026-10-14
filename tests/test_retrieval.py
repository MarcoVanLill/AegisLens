from __future__ import annotations

from dota_advisor.container import build_container


def test_fts_retrieval_respects_version_and_threat(settings) -> None:
    container = build_container(settings)
    passages = container.strategy_retriever.retrieve(
        hero="Phantom Assassin",
        role="carry",
        patch_version=settings.data_version,
        threat_tags=["physical burst", "evasion"],
        limit=4,
    )
    assert passages
    assert all(passage.patch_version == settings.data_version for passage in passages)
    assert any(passage.source_id == "demo-pa-physical-01" for passage in passages)


def test_unknown_patch_returns_no_documents(settings) -> None:
    container = build_container(settings)
    assert (
        container.strategy_retriever.retrieve(
            hero=None,
            role=None,
            patch_version="unknown",
            threat_tags=["silence"],
        )
        == []
    )
