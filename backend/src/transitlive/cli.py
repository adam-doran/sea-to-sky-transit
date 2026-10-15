"""Command line: transitlive {migrate,collect,replay,bundle,capture,openapi,api}."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
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

    replay_p = sub.add_parser(
        "replay", help="replay an archive (snapshot files, daily bundles or both) through the collector on a fake clock"
    )
    replay_p.add_argument("archive", help="archive root; bundles are read from its bundles/ folder")
    replay_p.add_argument("--speed", type=float, default=1.0, help="1 = real time, 0 = as fast as possible")
    replay_p.add_argument("--loop", action="store_true", help="start again from the beginning when done")

    bundle_p = sub.add_parser(
        "bundle",
        help="pack a UTC day of the archive into bundles/{system}/{date}.tar.zst and upload it if S3 is configured",
    )
    bundle_p.add_argument("--archive", default=os.environ.get("TRANSITLIVE_ARCHIVE", "archive"))
    bundle_p.add_argument("--date", type=dt.date.fromisoformat, help="YYYY-MM-DD, in UTC (default: yesterday, UTC)")

    capture_p = sub.add_parser("capture", help="record real feeds into an archive directory (no database)")
    capture_p.add_argument("archive")
    capture_p.add_argument("--minutes", type=float, default=10)

    sub.add_parser("openapi", help="print the API's OpenAPI schema (used to generate the web app's types)")

    api_p = sub.add_parser("api", help="serve the API")
    api_p.add_argument("--host", default="127.0.0.1")
    api_p.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)  # chatty at import time
    config = load_config(args.config)

    if args.command == "migrate":
        from transitlive.db.engine import ensure_partitions, make_engine, migrate

        migrate()
        ensure_partitions(make_engine())
        logging.info("database is up to date")

    elif args.command == "collect":
        from transitlive.collector.archive import Archive
        from transitlive.collector.bundles import S3Store
        from transitlive.collector.fetch import Fetcher
        from transitlive.collector.service import Collector
        from transitlive.db.engine import make_engine

        fetcher = Fetcher(config.collector.user_agent, config.collector.timeout_seconds)
        s3 = S3Store.from_settings(config.archive)
        collector = Collector(config, make_engine(), Archive(args.archive), fetcher, s3=s3)
        asyncio.run(collector.run())

    elif args.command == "bundle":
        import time

        from transitlive.collector.archive import Archive
        from transitlive.collector.bundles import S3Store, bundle_day, previous_utc_day

        archive = Archive(args.archive)
        day = args.date or previous_utc_day(time.time())
        s3 = S3Store.from_settings(config.archive)
        for system in config.systems:
            result = bundle_day(archive, system.slug, day)
            if result is None:
                logging.info("%s %s: nothing archived", system.slug, day)
                continue
            logging.info(
                "%s %s: %s, %d files, %.0f KB",
                system.slug,
                day,
                "bundled" if result.created else "already bundled",
                result.members,
                result.size / 1024,
            )
            if s3 is not None and not s3.upload(result.path, system.slug, day):
                logging.info("%s %s: already in s3://%s", system.slug, day, s3.bucket)

    elif args.command == "replay":
        from transitlive.collector.replay import Replayer
        from transitlive.db.engine import make_engine

        asyncio.run(Replayer(config, make_engine(), args.archive).run(speed=args.speed, loop=args.loop))

    elif args.command == "capture":
        from transitlive.collector.archive import Archive
        from transitlive.collector.capture import capture

        saved = asyncio.run(capture(config, Archive(args.archive), args.minutes))
        logging.info("saved %d snapshots to %s", saved, args.archive)

    elif args.command == "openapi":
        import json
        import sys

        from transitlive.api.app import create_app
        from transitlive.db.engine import make_engine

        # create_engine doesn't connect, so no database is needed here
        json.dump(create_app(config, make_engine()).openapi(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")

    elif args.command == "api":
        import uvicorn

        from transitlive.api.app import create_app

        uvicorn.run(create_app(config), host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
