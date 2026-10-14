from __future__ import annotations

import time
from typing import Any

from dota_advisor.companion import api_url_for, run_companion


class FakeServer:
    def __init__(self) -> None:
        self.should_exit = False
        self.force_exit = False
        self.started = False

    def run(self) -> None:
        self.started = True
        while not self.should_exit and not self.force_exit:
            time.sleep(0.001)


def test_api_url_uses_loopback_for_wildcard_bind() -> None:
    assert api_url_for("0.0.0.0", 8123) == "http://127.0.0.1:8123"
    assert api_url_for("::", 8123) == "http://127.0.0.1:8123"
    assert api_url_for("::1", 8123) == "http://[::1]:8123"


def test_companion_starts_and_stops_managed_server(settings) -> None:
    server = FakeServer()
    readiness_calls = 0
    popup_arguments: dict[str, Any] = {}

    def readiness_check(_api_url: str) -> bool:
        nonlocal readiness_calls
        readiness_calls += 1
        return readiness_calls > 1 and server.started

    def popup_launcher(**kwargs: Any) -> None:
        popup_arguments.update(kwargs)

    run_companion(
        settings,
        host="127.0.0.1",
        port=8123,
        readiness_check=readiness_check,
        server_factory=lambda _host, _port: server,
        popup_launcher=popup_launcher,
    )

    assert popup_arguments == {
        "api_url": "http://127.0.0.1:8123",
        "poll_seconds": 2.0,
        "always_on_top": True,
    }
    assert server.should_exit is True


def test_companion_attaches_to_existing_server(settings) -> None:
    popup_arguments: dict[str, Any] = {}

    def unexpected_server(_host: str, _port: int) -> FakeServer:
        raise AssertionError("A second server should not be created")

    run_companion(
        settings,
        readiness_check=lambda _api_url: True,
        server_factory=unexpected_server,
        popup_launcher=lambda **kwargs: popup_arguments.update(kwargs),
    )

    assert popup_arguments["api_url"].endswith(f":{settings.port}")
