from __future__ import annotations

import asyncio
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from pydantic import BaseModel, Field, ValidationError

from .models import MatchState, VisionObservation


class VisionExtractionError(RuntimeError):
    """A safe provider-facing extraction error that never contains credentials."""


class GeminiFieldConfidence(BaseModel):
    """Provider-safe object schema; Gemini Developer API rejects arbitrary dictionaries."""

    game_time_seconds: float = Field(default=0.0, ge=0.0, le=1.0)
    gold: float = Field(default=0.0, ge=0.0, le=1.0)
    level: float = Field(default=0.0, ge=0.0, le=1.0)
    inventory: float = Field(default=0.0, ge=0.0, le=1.0)
    visible_enemy_items: float = Field(default=0.0, ge=0.0, le=1.0)


class GeminiVisionResponse(BaseModel):
    """Structured response without JSON Schema ``additionalProperties`` keywords."""

    game_time_seconds: int | None = Field(default=None, ge=0, le=21600)
    gold: int | None = Field(default=None, ge=0, le=100000)
    level: int | None = Field(default=None, ge=1, le=30)
    inventory: list[str] | None = Field(default=None, max_length=20)
    visible_enemy_items: list[str] = Field(default_factory=list, max_length=30)
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    field_confidence: GeminiFieldConfidence
    warnings: list[str] = Field(default_factory=list, max_length=20)

    def to_observation(self) -> VisionObservation:
        payload = self.model_dump()
        payload["field_confidence"] = self.field_confidence.model_dump()
        return VisionObservation.model_validate(payload)


class LocalVisionExtractor:
    """Conservative local path and extension point for OCR/template recognition."""

    async def extract(
        self, crops: dict[str, Image.Image], manual_context: MatchState | None
    ) -> VisionObservation:
        await asyncio.to_thread(self.preprocess_crops, crops)
        return VisionObservation(
            extraction_confidence=0.0,
            field_confidence={
                "game_time_seconds": 0.0,
                "gold": 0.0,
                "level": 0.0,
                "inventory": 0.0,
                "visible_enemy_items": 0.0,
            },
            warnings=[
                "Local preprocessing completed, but OCR/item templates are not configured; "
                "trusted manual values were preserved."
            ],
        )

    @staticmethod
    def preprocess_crops(crops: dict[str, Image.Image]) -> dict[str, Image.Image]:
        processed: dict[str, Image.Image] = {}
        for name, image in crops.items():
            rgb = image.convert("RGB")
            array = np.asarray(rgb)
            lab = cv2.cvtColor(array, cv2.COLOR_RGB2LAB)
            luminance, channel_a, channel_b = cv2.split(lab)
            equalized = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(luminance)
            enhanced = cv2.cvtColor(cv2.merge((equalized, channel_a, channel_b)), cv2.COLOR_LAB2RGB)
            output = Image.fromarray(enhanced).filter(ImageFilter.SHARPEN)
            processed[name] = ImageEnhance.Contrast(output).enhance(1.25)
        return processed


class FakeVisionExtractor:
    def __init__(self, observation: VisionObservation | None = None) -> None:
        self.observation = observation or VisionObservation(
            game_time_seconds=900,
            gold=1800,
            level=11,
            inventory=["Power Treads", "Magic Wand"],
            extraction_confidence=0.95,
            field_confidence={
                "game_time_seconds": 0.95,
                "gold": 0.95,
                "level": 0.9,
                "inventory": 0.9,
                "visible_enemy_items": 0.8,
            },
        )

    async def extract(
        self, crops: dict[str, Image.Image], manual_context: MatchState | None
    ) -> VisionObservation:
        return self.observation.model_copy(deep=True)


class GeminiVisionExtractor:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_concurrency: int = 1,
    ) -> None:
        if not api_key:
            raise VisionExtractionError("Gemini is not configured; set GEMINI_API_KEY.")
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def extract(
        self, crops: dict[str, Image.Image], manual_context: MatchState | None
    ) -> VisionObservation:
        async with self._semaphore:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._extract_sync, crops, manual_context),
                    timeout=self.timeout_seconds,
                )
            except TimeoutError as exc:
                raise VisionExtractionError(
                    f"Gemini extraction exceeded the {self.timeout_seconds:g}s timeout."
                ) from exc
            except ValidationError as exc:
                raise VisionExtractionError(
                    "Gemini returned structured data that failed validation."
                ) from exc
            except VisionExtractionError:
                raise
            except Exception as exc:
                message = str(exc).casefold()
                if "429" in message or "rate" in message:
                    detail = "Gemini rate limit reached; the previous trusted state was preserved."
                elif "401" in message or "403" in message or "api key" in message:
                    detail = "Gemini authentication failed; verify GEMINI_API_KEY."
                else:
                    detail = (
                        "Gemini extraction failed transiently; the previous trusted state was "
                        "preserved."
                    )
                raise VisionExtractionError(detail) from exc

    def _extract_sync(
        self, crops: dict[str, Image.Image], manual_context: MatchState | None
    ) -> VisionObservation:
        from google.genai import types

        context = (
            manual_context.model_dump_json(
                include={"hero", "role", "enemy_heroes", "inventory", "gold", "game_time_seconds"}
            )
            if manual_context
            else "{}"
        )
        prompt = (
            "Read only facts visibly present in the supplied Dota 2 HUD crops. The crop name is "
            "written immediately before each image. Never infer hidden enemy inventory or unseen "
            "game state. Use null and low field confidence when a value is cropped, ambiguous, or "
            "unreadable. Item names must be visible in the inventory crop. Manual context is "
            "reference information "
            f"and must not be treated as visual evidence: {context}"
        )
        parts: list[object] = [types.Part.from_text(text=prompt)]
        for name in ("game_time", "gold", "inventory"):
            image = crops.get(name)
            if image is None:
                continue
            buffer = BytesIO()
            image.convert("RGB").save(buffer, format="PNG")
            parts.append(types.Part.from_text(text=f"HUD crop: {name}"))
            parts.append(types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/png"))
        response = self._client.models.generate_content(
            model=self.model,
            contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GeminiVisionResponse,
                temperature=0.0,
            ),
        )
        if not response.text:
            raise VisionExtractionError("Gemini returned no structured extraction data.")
        return GeminiVisionResponse.model_validate_json(response.text).to_observation()


class FallbackVisionExtractor:
    def __init__(self, primary: object, fallback: LocalVisionExtractor) -> None:
        self.primary = primary
        self.fallback = fallback

    async def extract(
        self, crops: dict[str, Image.Image], manual_context: MatchState | None
    ) -> VisionObservation:
        try:
            return await self.primary.extract(crops, manual_context)  # type: ignore[attr-defined]
        except VisionExtractionError as exc:
            observation = await self.fallback.extract(crops, manual_context)
            observation.warnings.insert(0, str(exc))
            return observation
