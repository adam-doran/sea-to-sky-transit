"""Command line: transitlive {migrate,collect,replay,capture,api}."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

from transitlive.config import load_config


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="transitlive", description=__doc__)
    parser.add_argument("--config", help="path to systems.toml (default: config/systems.toml)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="create or upgrade the database schema")

    collect_p = sub.add_parser("collect", help="run the collector against BC Transit")
    collect_p.add_argument("--archive", default=os.environ.get("TRANSITLIVE_ARCHIVE", "archive"))

    replay_p = sub.add_parser("replay", help="replay an archive through the collector on a fake clock")
    replay_p.add_argument("archive")
    replay_p.add_argument("--speed", type=float, default=1.0, help="1 = real time, 0 = as fast as possible")
    replay_p.add_argument("--loop", action="store_true", help="start again from the beginning when done")

    capture_p = sub.add_parser("capture", help="record real feeds into an archive directory (no database)")
    capture_p.add_argument("archive")
    capture_p.add_argument("--minutes", type=float, default=10)

    api_p = sub.add_parser("api", help="serve the API")
    api_p.add_argument("--host", default="127.0.0.1")
    api_p.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    config = load_config(args.config)

    if args.command == "migrate":
        from transitlive.db.engine import ensure_partitions, make_engine, migrate

        migrate()
        ensure_partitions(make_engine())
        logging.info("database is up to date")

    elif args.command == "collect":
        from transitlive.collector.archive import Archive
        from transitlive.collector.fetch import Fetcher
        from transitlive.collector.service import Collector
        from transitlive.db.engine import make_engine

        fetcher = Fetcher(config.collector.user_agent, config.collector.timeout_seconds)
        collector = Collector(config, make_engine(), Archive(args.archive), fetcher)
        asyncio.run(collector.run())

    elif args.command == "replay":
        from transitlive.collector.replay import Replayer
        from transitlive.db.engine import make_engine

        asyncio.run(Replayer(config, make_engine(), args.archive).run(speed=args.speed, loop=args.loop))

    elif args.command == "capture":
        from transitlive.collector.archive import Archive
        from transitlive.collector.capture import capture

        saved = asyncio.run(capture(config, Archive(args.archive), args.minutes))
        logging.info("saved %d snapshots to %s", saved, args.archive)

    elif args.command == "api":
        import uvicorn

        from transitlive.api.app import create_app

        uvicorn.run(create_app(config), host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
