from __future__ import annotations

from dota_advisor.vision import GeminiVisionResponse


def test_gemini_schema_avoids_unsupported_additional_properties() -> None:
    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {key for child in value.values() for key in keys(child)}
        if isinstance(value, list):
            return {key for child in value for key in keys(child)}
        return set()

    assert "additionalProperties" not in keys(GeminiVisionResponse.model_json_schema())
