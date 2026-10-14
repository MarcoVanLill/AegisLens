from __future__ import annotations

from fastapi.testclient import TestClient

from dota_advisor.api import create_app
from dota_advisor.container import build_container
from dota_advisor.vision import FakeVisionExtractor


def test_health_manual_state_and_recommendations(settings) -> None:
    app = create_app(build_container(settings, vision_extractor=FakeVisionExtractor()))
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        catalog = client.get("/api/v1/catalog").json()
        assert catalog["catalog_item_count"] == 276
        assert catalog["recommendable_item_count"] == 22
        response = client.put(
            "/api/v1/state/manual",
            json={
                "hero": "Juggernaut",
                "role": "carry",
                "game_time_seconds": 1200,
                "gold": 1800,
                "level": 12,
                "inventory": ["Power Treads"],
                "enemy_heroes": ["Crystal Maiden", "Riki"],
            },
        )
        assert response.status_code == 200
        assert response.json()["source"] == "manual"

        response = client.post("/api/v1/recommendations")
        assert response.status_code == 200
        assert len(response.json()["recommendations"]) == 3
        assert client.get("/api/v1/retrieval/latest").json()


def test_prevents_recommendation_without_manual_hero(settings) -> None:
    app = create_app(build_container(settings, vision_extractor=FakeVisionExtractor()))
    with TestClient(app) as client:
        response = client.post("/api/v1/recommendations")
    assert response.status_code == 409


def test_calibration_round_trip(settings) -> None:
    app = create_app(build_container(settings, vision_extractor=FakeVisionExtractor()))
    with TestClient(app) as client:
        configuration = client.get("/api/v1/regions").json()
        configuration["notes"] = "adjusted by test"
        response = client.put("/api/v1/regions", json=configuration)
        assert response.status_code == 200
        assert client.get("/api/v1/regions").json()["notes"] == "adjusted by test"


def test_compact_companion_page(settings) -> None:
    app = create_app(build_container(settings, vision_extractor=FakeVisionExtractor()))
    with TestClient(app) as client:
        response = client.get("/compact")
    assert response.status_code == 200
    assert "What to buy next" in response.text
    assert "/static/compact.js" in response.text
