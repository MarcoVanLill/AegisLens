from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
from pathlib import Path

import uvicorn
from pydantic import TypeAdapter

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

    ingest = subcommands.add_parser("ingest", help="Ingest strategy documents from a JSON array")
    ingest.add_argument("path", type=Path)

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
    elif args.command == "ingest":
        _ingest(settings, args.path)
    elif args.command == "reset-db":
        _reset_database(settings)
    else:
        raise RuntimeError(f"Unsupported command: {json.dumps(args.command)}")


if __name__ == "__main__":
    main()
