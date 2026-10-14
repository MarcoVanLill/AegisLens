from __future__ import annotations

from PIL import Image, ImageDraw

from dota_advisor.container import build_container
from dota_advisor.models import ManualStateInput, Role, VisionObservation
from dota_advisor.vision import FakeVisionExtractor


def _visible_test_image() -> Image.Image:
    image = Image.new("RGB", (1920, 1080), "#14283a")
    draw = ImageDraw.Draw(image)
    draw.rectangle((300, 200, 1600, 800), fill="#6b2833")
    draw.text((900, 20), "15:00", fill="white")
    return image


async def test_low_confidence_preserves_trusted_manual_fields(settings) -> None:
    observation = VisionObservation(
        game_time_seconds=999,
        gold=9999,
        inventory=["Impossible Item"],
        extraction_confidence=0.3,
        field_confidence={
            "game_time_seconds": 0.3,
            "gold": 0.3,
            "level": 0.3,
            "inventory": 0.3,
            "visible_enemy_items": 0.3,
        },
    )
    container = build_container(settings, vision_extractor=FakeVisionExtractor(observation))
    container.advisor.set_manual_state(
        ManualStateInput(
            hero="Axe",
            role=Role.OFFLANE,
            game_time_seconds=600,
            gold=1200,
            inventory=["Vanguard"],
            enemy_heroes=["Juggernaut"],
        )
    )
    outcome = await container.advisor.process_image(_visible_test_image(), force=True)
    assert outcome.state.gold == 1200
    assert outcome.state.game_time_seconds == 600
    assert outcome.state.inventory == ["Vanguard"]
    assert any("below" in warning for warning in outcome.warnings)


async def test_high_confidence_updates_visible_fields(settings) -> None:
    observation = VisionObservation(
        game_time_seconds=900,
        gold=2300,
        inventory=["Blink Dagger"],
        extraction_confidence=0.95,
        field_confidence={
            "game_time_seconds": 0.95,
            "gold": 0.95,
            "level": 0.2,
            "inventory": 0.9,
            "visible_enemy_items": 0.2,
        },
    )
    container = build_container(settings, vision_extractor=FakeVisionExtractor(observation))
    container.advisor.set_manual_state(
        ManualStateInput(
            hero="Axe",
            role=Role.OFFLANE,
            game_time_seconds=600,
            gold=1200,
            inventory=[],
            enemy_heroes=["Juggernaut"],
        )
    )
    outcome = await container.advisor.process_image(_visible_test_image(), force=True)
    assert outcome.state.gold == 2300
    assert outcome.state.game_time_seconds == 900
    assert outcome.state.inventory == ["Blink Dagger"]
