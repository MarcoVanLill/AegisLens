from __future__ import annotations

import json
from pathlib import Path

import pytest

from dota_advisor.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    regions_path = tmp_path / "hud_regions.json"
    regions_path.write_text(
        json.dumps(
            {
                "layout_id": "test-layout",
                "reference_resolution": [1920, 1080],
                "notes": "test",
                "regions": {
                    "inventory": {"x": 0.7, "y": 0.7, "width": 0.25, "height": 0.25},
                    "gold": {"x": 0.7, "y": 0.6, "width": 0.1, "height": 0.08},
                    "game_time": {"x": 0.45, "y": 0.0, "width": 0.1, "height": 0.08},
                },
            }
        ),
        encoding="utf-8",
    )
    return Settings(
        _env_file=None,
        database_path=tmp_path / "advisor.db",
        regions_path=regions_path,
        debug_directory=tmp_path / "debug",
        debug_save_crops=False,
        recommendation_cooldown_seconds=0,
        gemini_api_key=None,
    )
