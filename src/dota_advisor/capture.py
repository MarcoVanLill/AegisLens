from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import cv2
import mss
import numpy as np
from PIL import Image

from .models import (
    AnalysisOutcome,
    CaptureStatus,
    MonitorInfo,
    NormalizedRegion,
    RegionConfiguration,
)


class ScreenCaptureError(RuntimeError):
    """An actionable screen-capture error."""


class CaptureService:
    def __init__(self, regions_path: Path, debug_directory: Path) -> None:
        self.regions_path = regions_path
        self.debug_directory = debug_directory

    def load_regions(self) -> RegionConfiguration:
        if not self.regions_path.exists():
            raise ScreenCaptureError(
                f"HUD region configuration was not found at {self.regions_path}. "
                "Copy config/hud_regions.json or set DOTA_ADVISOR_REGIONS_PATH."
            )
        return RegionConfiguration.model_validate_json(
            self.regions_path.read_text(encoding="utf-8")
        )

    def save_regions(self, configuration: RegionConfiguration) -> None:
        self.regions_path.parent.mkdir(parents=True, exist_ok=True)
        self.regions_path.write_text(
            json.dumps(configuration.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )

    def enumerate_monitors(self) -> list[MonitorInfo]:
        try:
            with mss.mss() as grabber:
                monitors = list(grabber.monitors)
        except Exception as exc:
            raise ScreenCaptureError(f"Windows monitor enumeration failed: {exc}") from exc
        return [
            MonitorInfo(
                index=index,
                left=int(monitor["left"]),
                top=int(monitor["top"]),
                width=int(monitor["width"]),
                height=int(monitor["height"]),
                primary=index == 1,
            )
            for index, monitor in enumerate(monitors[1:], start=1)
        ]

    def capture_monitor(self, monitor_index: int) -> Image.Image:
        try:
            with mss.mss() as grabber:
                if monitor_index < 1 or monitor_index >= len(grabber.monitors):
                    raise ScreenCaptureError(
                        f"Monitor {monitor_index} is unavailable. Select a monitor listed by "
                        "/api/v1/monitors."
                    )
                shot = grabber.grab(grabber.monitors[monitor_index])
                image = Image.frombytes("RGB", shot.size, shot.rgb)
        except ScreenCaptureError:
            raise
        except Exception as exc:
            raise ScreenCaptureError(
                "Screen capture failed. On Windows, run Dota 2 in borderless-windowed mode "
                f"and verify that the selected display is active. Details: {exc}"
            ) from exc
        self.assert_visible(image)
        return image

    @staticmethod
    def assert_visible(image: Image.Image) -> None:
        sample = np.asarray(image.convert("L").resize((128, 72)), dtype=np.float32)
        mean = float(sample.mean())
        standard_deviation = float(sample.std())
        if mean < 4.0 or standard_deviation < 2.0:
            raise ScreenCaptureError(
                "The captured image is black or nearly uniform. Use Dota 2 borderless-windowed "
                "mode, keep the game visible on the selected monitor, and check Windows capture "
                "permissions."
            )

    def crop_regions(self, image: Image.Image) -> dict[str, Image.Image]:
        configuration = self.load_regions()
        width, height = image.size
        crops: dict[str, Image.Image] = {}
        for name, region in configuration.regions.items():
            box = self._pixel_box(region, width, height)
            crops[name] = image.crop(box)
        return crops

    @staticmethod
    def _pixel_box(region: NormalizedRegion, width: int, height: int) -> tuple[int, int, int, int]:
        left = round(region.x * width)
        top = round(region.y * height)
        right = round((region.x + region.width) * width)
        bottom = round((region.y + region.height) * height)
        return left, top, right, bottom

    def save_debug_crops(self, crops: dict[str, Image.Image]) -> dict[str, str]:
        self.debug_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        urls: dict[str, str] = {}
        for name, crop in crops.items():
            filename = f"{timestamp}-{name}.png"
            crop.save(self.debug_directory / filename, format="PNG")
            urls[name] = f"/debug/{filename}"
        return urls


class ChangeDetector:
    def __init__(self, threshold: float = 0.025) -> None:
        self.threshold = threshold
        self._previous: dict[str, np.ndarray] = {}
        self.last_change_score = 1.0

    @staticmethod
    def preprocess(image: Image.Image) -> np.ndarray:
        grayscale = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
        resized = cv2.resize(grayscale, (96, 48), interpolation=cv2.INTER_AREA)
        return cv2.GaussianBlur(resized, (3, 3), 0)

    def has_meaningful_change(self, crops: dict[str, Image.Image]) -> bool:
        current = {name: self.preprocess(image) for name, image in crops.items()}
        if not self._previous:
            self._previous = current
            self.last_change_score = 1.0
            return True
        scores = []
        for name, image in current.items():
            previous = self._previous.get(name)
            if previous is None:
                scores.append(1.0)
            else:
                scores.append(float(cv2.absdiff(previous, image).mean()) / 255.0)
        self._previous = current
        self.last_change_score = max(scores, default=0.0)
        return self.last_change_score >= self.threshold

    def reset(self) -> None:
        self._previous.clear()
        self.last_change_score = 1.0


CaptureProcessor = Callable[[Image.Image], Awaitable[AnalysisOutcome]]


class CaptureLoop:
    def __init__(
        self,
        capture_service: CaptureService,
        processor: CaptureProcessor,
        *,
        default_monitor: int,
        default_interval: float,
    ) -> None:
        self.capture_service = capture_service
        self.processor = processor
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._status = CaptureStatus(
            running=False,
            monitor_index=default_monitor,
            interval_seconds=default_interval,
        )

    @property
    def status(self) -> CaptureStatus:
        return self._status.model_copy(deep=True)

    def set_debug_crops(self, debug_crops: dict[str, str]) -> None:
        self._status.debug_crops = debug_crops

    async def start(self, monitor_index: int, interval_seconds: float) -> CaptureStatus:
        if self._task and not self._task.done():
            raise ScreenCaptureError("A capture loop is already running.")
        available = {monitor.index for monitor in self.capture_service.enumerate_monitors()}
        if monitor_index not in available:
            raise ScreenCaptureError(f"Monitor {monitor_index} is not available.")
        self._stop_event = asyncio.Event()
        self._status = CaptureStatus(
            running=True,
            monitor_index=monitor_index,
            interval_seconds=interval_seconds,
        )
        self._task = asyncio.create_task(self._run(), name="dota-advisor-capture-loop")
        return self.status

    async def stop(self) -> CaptureStatus:
        self._stop_event.set()
        task = self._task
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._task = None
        self._status.running = False
        return self.status

    async def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                started = asyncio.get_running_loop().time()
                try:
                    image = await asyncio.to_thread(
                        self.capture_service.capture_monitor, self._status.monitor_index
                    )
                    self._status.capture_count += 1
                    self._status.last_capture_at = datetime.now(UTC)
                    outcome = await self.processor(image)
                    if outcome.skipped_unchanged:
                        self._status.skipped_unchanged_count += 1
                    else:
                        self._status.analysis_count += 1
                        self._status.last_analysis_at = datetime.now(UTC)
                        self._status.last_analysis_warnings = outcome.warnings
                    self._status.last_error = None
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._status.last_error = str(exc)
                elapsed = asyncio.get_running_loop().time() - started
                delay = max(0.0, self._status.interval_seconds - elapsed)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
        finally:
            self._status.running = False
