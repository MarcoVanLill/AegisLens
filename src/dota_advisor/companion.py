from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Protocol

import uvicorn

from .config import Settings


class CompanionServer(Protocol):
    should_exit: bool
    force_exit: bool

    def run(self) -> None: ...


ReadinessCheck = Callable[[str], bool]
PopupLauncher = Callable[..., None]
ServerFactory = Callable[[str, int], CompanionServer]


def api_url_for(host: str, port: int) -> str:
    client_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    if ":" in client_host and not client_host.startswith("["):
        client_host = f"[{client_host}]"
    return f"http://{client_host}:{port}"


def api_is_ready(api_url: str) -> bool:
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/health/ready",
        headers={"User-Agent": "AegisLens companion"},
    )
    try:
        with urllib.request.urlopen(request, timeout=0.5) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _server_factory(host: str, port: int) -> CompanionServer:
    config = uvicorn.Config(
        "dota_advisor.main:app",
        host=host,
        port=port,
        log_level="info",
    )
    return uvicorn.Server(config)


def _wait_until_ready(
    api_url: str,
    server_thread: threading.Thread,
    readiness_check: ReadinessCheck,
    startup_timeout: float,
) -> None:
    deadline = time.monotonic() + startup_timeout
    while time.monotonic() < deadline:
        if readiness_check(api_url):
            return
        if not server_thread.is_alive():
            raise RuntimeError(
                "The local AegisLens API stopped during startup. "
                "Check the server output above for the cause."
            )
        time.sleep(0.1)
    raise RuntimeError(
        f"The local AegisLens API did not become ready at {api_url} "
        f"within {startup_timeout:g} seconds."
    )


def run_companion(
    settings: Settings,
    *,
    host: str | None = None,
    port: int | None = None,
    poll_seconds: float = 2.0,
    always_on_top: bool = True,
    startup_timeout: float = 15.0,
    readiness_check: ReadinessCheck = api_is_ready,
    server_factory: ServerFactory = _server_factory,
    popup_launcher: PopupLauncher | None = None,
) -> None:
    bind_host = host or settings.host
    bind_port = port or settings.port
    api_url = api_url_for(bind_host, bind_port)

    if popup_launcher is None:
        from .popup import launch_popup

        popup_launcher = launch_popup

    if readiness_check(api_url):
        popup_launcher(
            api_url=api_url,
            poll_seconds=poll_seconds,
            always_on_top=always_on_top,
        )
        return

    server = server_factory(bind_host, bind_port)
    server_thread = threading.Thread(
        target=server.run,
        name="aegislens-api",
        daemon=True,
    )
    server_thread.start()

    try:
        _wait_until_ready(api_url, server_thread, readiness_check, startup_timeout)
        popup_launcher(
            api_url=api_url,
            poll_seconds=poll_seconds,
            always_on_top=always_on_top,
        )
    finally:
        server.should_exit = True
        server_thread.join(timeout=5.0)
        if server_thread.is_alive():
            server.force_exit = True
            server_thread.join(timeout=1.0)
