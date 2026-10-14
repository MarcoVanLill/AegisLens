from __future__ import annotations

from PIL import Image, ImageDraw

from dota_advisor.capture import ChangeDetector, ScreenCaptureError


def _image(color: str) -> Image.Image:
    return Image.new("RGB", (200, 100), color)


def test_change_detector_skips_identical_crops() -> None:
    detector = ChangeDetector(threshold=0.02)
    crops = {"gold": _image("navy"), "inventory": _image("green")}
    assert detector.has_meaningful_change(crops)
    assert not detector.has_meaningful_change(crops)


def test_change_detector_notices_visible_change() -> None:
    detector = ChangeDetector(threshold=0.01)
    original = _image("navy")
    changed = original.copy()
    ImageDraw.Draw(changed).rectangle((0, 0, 120, 100), fill="white")
    assert detector.has_meaningful_change({"gold": original})
    assert detector.has_meaningful_change({"gold": changed})


def test_black_frame_has_actionable_error() -> None:
    from dota_advisor.capture import CaptureService

    try:
        CaptureService.assert_visible(_image("black"))
    except ScreenCaptureError as exc:
        assert "borderless-windowed" in str(exc)
    else:
        raise AssertionError("Expected a black-frame capture error")
