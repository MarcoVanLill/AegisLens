from __future__ import annotations

import pytest
from pydantic import ValidationError

from dota_advisor.models import MatchState, RegionConfiguration, VisionObservation


def test_match_state_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        MatchState(extraction_confidence=1.2)


def test_vision_output_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        VisionObservation(
            extraction_confidence=0.9,
            field_confidence={},
            hidden_enemy_inventory=["Black King Bar"],
        )


def test_regions_must_stay_inside_normalized_frame() -> None:
    with pytest.raises(ValidationError):
        RegionConfiguration.model_validate(
            {
                "layout_id": "bad",
                "reference_resolution": [1920, 1080],
                "regions": {
                    "inventory": {"x": 0.9, "y": 0.9, "width": 0.2, "height": 0.2},
                    "gold": {"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.1},
                    "game_time": {"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.1},
                },
            }
        )
