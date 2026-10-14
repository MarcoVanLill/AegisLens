from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
from pathlib import Path

import uvicorn
from pydantic import TypeAdapter

from .catalog import FandomCatalogClient
from .config import Settings
from .container import build_container
from .models import StrategyDocument


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Dota 2 item-advisor commands")
    subcommands = parser.add_subparsers(dest="command", required=True)

    serve = subcommands.add_parser("serve", help="Start the local FastAPI server")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true")

    once = subcommands.add_parser("capture-once", help="Capture and analyze one monitor frame")
    once.add_argument("--monitor", type=int, default=None)
    once.add_argument("--force", action="store_true")

    watch = subcommands.add_parser("watch", help="Run continuous capture without the web server")
    watch.add_argument("--monitor", type=int, default=None)
    watch.add_argument("--interval", type=float, default=None)

    popup = subcommands.add_parser(
        "popup",
        help="Open the native always-on-top recommendation companion",
    )
    popup.add_argument("--api-url", default=None)
    popup.add_argument("--poll-seconds", type=float, default=2.0)
    popup.add_argument("--no-topmost", action="store_true")

    companion = subcommands.add_parser(
        "companion",
        help="Start the local API and always-on-top popup together",
    )
    companion.add_argument("--host", default=None)
    companion.add_argument("--port", type=int, default=None)
    companion.add_argument("--poll-seconds", type=float, default=2.0)
    companion.add_argument("--no-topmost", action="store_true")

    ingest = subcommands.add_parser("ingest", help="Ingest strategy documents from a JSON array")
    ingest.add_argument("path", type=Path)

    subcommands.add_parser(
        "sync-items",
        help="Refresh the bundled item catalog from the Fandom Cargo table",
    )

    subcommands.add_parser("reset-db", help="Delete and rebuild only the configured local database")
    return parser


async def _capture_once(settings: Settings, monitor: int | None, force: bool) -> None:
    container = build_container(settings)
    try:
        result = await container.advisor.capture_once(
            monitor or settings.monitor_index,
            force=force,
        )
        print(result.model_dump_json(indent=2))
    finally:
        await container.advisor.shutdown()


async def _watch(settings: Settings, monitor: int | None, interval: float | None) -> None:
    container = build_container(settings)
    await container.advisor.capture_loop.start(
        monitor or settings.monitor_index,
        interval or settings.capture_interval_seconds,
    )
    print("Capture watch is running. Press Ctrl+C to stop.")
    try:
        while True:
            await asyncio.sleep(1.0)
            status = container.advisor.capture_loop.status
            if status.last_error:
                print(f"Capture warning: {status.last_error}")
    finally:
        await container.advisor.shutdown()


def _ingest(settings: Settings, path: Path) -> None:
    documents = TypeAdapter(list[StrategyDocument]).validate_json(path.read_text(encoding="utf-8"))
    container = build_container(settings)
    count = container.strategy_retriever.ingest(documents)
    print(f"Ingested {count} strategy documents from {path}.")


def _reset_database(settings: Settings) -> None:
    database_path = settings.database_path.resolve()
    candidates = [
        database_path,
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            candidate.unlink()
    build_container(settings)
    print(f"Rebuilt {database_path} with {settings.data_version} demonstration data.")


def _sync_items(settings: Settings) -> None:
    snapshot = FandomCatalogClient().refresh_bundled_snapshot()
    container = build_container(settings)
    print(
        f"Refreshed {snapshot.item_count} item records from {snapshot.source_url} "
        f"and rebuilt {container.database.path}."
    )


def main() -> None:
    args = _parser().parse_args()
    settings = Settings()
    if args.command == "serve":
        uvicorn.run(
            "dota_advisor.main:app",
            host=args.host or settings.host,
            port=args.port or settings.port,
            reload=args.reload,
        )
    elif args.command == "capture-once":
        asyncio.run(_capture_once(settings, args.monitor, args.force))
    elif args.command == "watch":
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(_watch(settings, args.monitor, args.interval))
    elif args.command == "popup":
        from .popup import launch_popup

        client_host = "127.0.0.1" if settings.host in {"0.0.0.0", "::"} else settings.host
        launch_popup(
            api_url=args.api_url or f"http://{client_host}:{settings.port}",
            poll_seconds=args.poll_seconds,
            always_on_top=not args.no_topmost,
        )
    elif args.command == "companion":
        from .companion import run_companion

        try:
            run_companion(
                settings,
                host=args.host,
                port=args.port,
                poll_seconds=args.poll_seconds,
                always_on_top=not args.no_topmost,
            )
        except (RuntimeError, ValueError) as exc:
            raise SystemExit(f"Unable to start the AegisLens companion: {exc}") from exc
    elif args.command == "ingest":
        _ingest(settings, args.path)
    elif args.command == "sync-items":
        _sync_items(settings)
    elif args.command == "reset-db":
        _reset_database(settings)
    else:
        raise RuntimeError(f"Unsupported command: {json.dumps(args.command)}")


if __name__ == "__main__":
    main()
