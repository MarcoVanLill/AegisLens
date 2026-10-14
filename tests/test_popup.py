from __future__ import annotations

from dota_advisor.popup import _format_game_time, _format_updated_at, format_recommendation


def test_popup_recommendation_formats_affordable_component() -> None:
    result = format_recommendation(
        {
            "item_name": "Black King Bar",
            "total_score": 0.876,
            "next_component": "Ogre Axe",
            "additional_gold_required": 0,
            "reason": "Useful against repeated disables.",
            "addressed_threats": ["silence", "repeated disables"],
        }
    )
    assert result.target_name == "Black King Bar"
    assert result.purchase_name == "Ogre Axe"
    assert result.availability == "buy now"


def test_popup_recommendation_formats_gold_still_needed() -> None:
    result = format_recommendation(
        {
            "item_name": "Pipe of Insight",
            "total_score": 0.5,
            "next_component": "Hood of Defiance",
            "additional_gold_required": 325,
            "reason": "Team magic defense.",
            "addressed_threats": [],
        }
    )
    assert result.purchase_name == "Hood of Defiance"
    assert result.availability == "need 325g"


def test_popup_time_helpers() -> None:
    assert _format_game_time(905) == "15:05"
    assert _format_updated_at(None) == "Not updated"
